"""ANA-089 (per-session benchmark DB), ANA-091 (cache declaration guard), ANA-133 (metrics trim)."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from app.benchmark import persist
from app.database.db import Database
from app.database.retention import expand_metrics, trim_metrics


def _run(db, rid, session, cache=0, **kw):
    db.save_run({"run_id": rid, "session_id": session, "created_at": time.time(), "query": "q",
                 "pipeline": "baseline", "cache_enabled": cache, "metrics_json": {"x": 1}, **kw})


# ------------------------------------------------------------------ ANA-089
def test_bench_db_path_is_separate_and_sanitised(tmp_path):
    prod = tmp_path / "benchmark.db"
    p = persist.bench_db_path("opt-2026/09:27 ../x", prod)
    assert p.parent == tmp_path / "bench_sessions" and p != prod
    assert ".." not in p.name and "/" not in p.name and ":" not in p.name
    with pytest.raises(ValueError):
        persist.bench_db_path("///", prod)


def test_isolated_session_leaves_production_ledger_clean(tmp_path):
    prod = Database(tmp_path / "benchmark.db")
    _run(prod, "p1", "adhoc")
    prod.create_session("adhoc", "search", {})
    bench = persist.open_bench_db("bench-1", tmp_path / "benchmark.db")
    bench.create_session("bench-1", "retrieval", {})
    _run(bench, "b1", "bench-1")
    assert persist.production_benchmark_runs(prod) == 0                  # metric: 0 in production
    assert persist.production_benchmark_runs(bench) == 1
    assert prod.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 1
    assert (tmp_path / "bench_sessions" / "bench-1.db").exists()


def test_attach_for_analysis_is_read_only(tmp_path):
    prod = Database(tmp_path / "benchmark.db")
    bench = persist.open_bench_db("b", tmp_path / "benchmark.db")
    _run(bench, "b1", "b")
    bench.close()
    alias = persist.attach_for_analysis(prod.conn, tmp_path / "bench_sessions" / "b.db")
    assert prod.conn.execute(f"SELECT COUNT(*) FROM {alias}.runs").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError):
        prod.conn.execute(f"DELETE FROM {alias}.runs")
    with pytest.raises(ValueError):
        persist.attach_for_analysis(prod.conn, tmp_path / "x.db", "bad alias; drop")


# ------------------------------------------------------------------ ANA-091
def test_cache_on_without_declaration_is_refused():
    with pytest.raises(persist.CacheNotDeclaredError, match="--allow-cache"):
        persist.require_cache_declared(True, False)


def test_declaration_is_recorded():
    assert persist.require_cache_declared(True, True, "ns1") == {
        "cache_enabled": True, "allow_cache": True, "cache_namespace": "ns1"}
    assert persist.require_cache_declared(False, False)["cache_enabled"] is False


def test_audit_finds_undeclared_cache_sessions(tmp_path):
    d = Database(tmp_path / "t.db")
    d.create_session("bad", "opt_benchmark", {"cache_enabled": True})
    d.create_session("ok", "opt_benchmark", {"cache_enabled": True, "allow_cache": True})
    d.create_session("clean", "retrieval", {})
    d.create_session("adhoc", "search", {})
    for sid in ("bad", "ok", "adhoc"):
        _run(d, f"r-{sid}", sid, cache=1)
    _run(d, "r-clean", "clean", cache=0)
    found = persist.undeclared_cache_sessions(d)
    assert [f["session_id"] for f in found] == ["bad"]                   # adhoc traffic is not a comparison


def test_config_hash_is_stable():
    assert persist.config_hash({"a": 1, "b": 2}) == persist.config_hash({"b": 2, "a": 1})
    assert persist.config_hash({"a": 1}) != persist.config_hash({"a": 2})


def test_persist_script_refuses_undeclared_cache(tmp_path, monkeypatch):
    import runpy
    import sys
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.setenv("BENCHMARK_MODE", "false")
    monkeypatch.setenv("PROFILE", "production")
    monkeypatch.setattr(sys, "argv", ["persist_benchmark.py", "--session", "t1"])
    from app.gateway import memory_gateway as mg
    monkeypatch.setattr(mg.MemoryGateway, "warm", lambda self: {})
    with pytest.raises(SystemExit) as ei:
        runpy.run_path(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"
                           / "persist_benchmark.py"), run_name="__main__")
    assert ei.value.code == 2


# ------------------------------------------------------------------ ANA-133
def _metrics():
    layers = {"lookups": 6, "hits_l1": 0, "misses": 6}
    return {"jev_cost": 0.1, "cache_layers": layers, "opt_flags": ["a", "b"],
            "jev": {"jev_model": "m", "cache_layers": dict(layers), "opt_flags": ["a", "b"], "latency_ms": 5}}


def test_trim_is_lossless_and_smaller():
    m = _metrics()
    t = trim_metrics(m)
    assert t is not m and "cache_layers" not in t["jev"] and t["_trimmed"] == ["cache_layers", "opt_flags"]
    assert len(json.dumps(t)) < len(json.dumps(m))
    assert expand_metrics(dict(t, jev=dict(t["jev"]))) == m
    assert m["jev"]["cache_layers"]                                     # input not mutated


def test_trim_keeps_blocks_that_differ():
    m = _metrics()
    m["jev"]["cache_layers"] = {"different": 1}
    t = trim_metrics(m)
    assert "cache_layers" in t["jev"] and t["_trimmed"] == ["opt_flags"]


def test_trim_flag_off_by_default_and_roundtrip_when_on(tmp_path, monkeypatch):
    d = Database(tmp_path / "t.db")
    monkeypatch.delenv("ANAMNESIA_METRICS_TRIM", raising=False)
    _run(d, "off", "s", metrics_json=_metrics())
    assert "_trimmed" not in d.query("SELECT metrics_json m FROM runs WHERE run_id='off'")[0]["m"]
    monkeypatch.setenv("ANAMNESIA_METRICS_TRIM", "1")
    _run(d, "on", "s", metrics_json=_metrics())
    raw = d.query("SELECT metrics_json m FROM runs WHERE run_id='on'")[0]["m"]
    assert "_trimmed" in raw and len(raw) < len(d.query("SELECT metrics_json m FROM runs WHERE run_id='off'")[0]["m"])
    run = d.get_run("on")
    assert run and run["metrics"] == _metrics()                         # transparent through the API
