"""Onda 7 (ANA-202/208/210/213): alertas de regressão, saúde dos provedores, linhagem de notas, prévia sem gravar run."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import costs as costs_api
from app.api import dashboard_insights as di_api
from app.api import memory_store as store_api
from app.api import settings as settings_api
from app.database.db import Database
from app.services import dashboard_insights as ins
from app.services.security import get_or_create_local_token
from tests.test_costs_ledger import mk_run

ROOT = Path(__file__).resolve().parents[1]


def run(i, pipeline="baseline", *, ctx=100, lat=10.0, created=None, error=None, provider=None, agent="mcp", sources=None, **m):
    r = mk_run(f"r{pipeline[:3]}{i}", pipeline, created_at=created if created is not None else 1_000_000 + i,
               context_tokens=ctx, total_latency_ms=lat, **m)
    r["agent"], r["provider"], r["error"] = agent, provider, error
    if sources is not None:
        r["sources_json"] = sources
    return r


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("MG_METRICS_ONLY", raising=False)
    db = Database(tmp_path / "o7.db")
    app = FastAPI()
    for mod in (di_api, settings_api, store_api):
        app.include_router(mod.router)
    app.dependency_overrides[costs_api.get_db] = lambda: db
    app.dependency_overrides[settings_api.get_db] = lambda: db
    tc = TestClient(app, client=("127.0.0.1", 50000), headers={"X-MG-Token": get_or_create_local_token()})
    yield tc, db
    db.conn.close()


# -- ANA-202 ---------------------------------------------------------------------------------------
def _rows(prev_ctx, cur_ctx, n=6, **kw):
    """newest-first as db.list_runs returns: first the current window, then the previous one."""
    return ([dict(run(100 + i, ctx=cur_ctx, **kw), metrics={"context_tokens": cur_ctx, "total_latency_ms": kw.get("lat", 10.0)}) for i in range(n)]
            + [dict(run(i, ctx=prev_ctx, **kw), metrics={"context_tokens": prev_ctx, "total_latency_ms": kw.get("lat", 10.0)}) for i in range(n)])


def test_regression_flags_only_beyond_threshold():
    rep = ins.regression_alerts(_rows(100, 130), window=6)
    [al] = [a for a in rep["alerts"] if a["metric"] == "context_tokens"]
    assert al["pipeline"] == "baseline" and al["change_pct"] == 30.0 and al["severity"] == "warning"
    assert not ins.regression_alerts(_rows(100, 110), window=6)["alerts"]            # +10% < 20% default
    assert ins.regression_alerts(_rows(100, 110), window=6, thresholds={"tokens_pct": 5})["alerts"]
    crit = ins.regression_alerts(_rows(100, 200), window=6)["alerts"][0]
    assert crit["severity"] == "critical"


def test_regression_never_reports_ok_without_data():
    rep = ins.regression_alerts(_rows(100, 500, n=3), window=5)                     # < MIN_RUNS per window
    assert rep["alerts"] == [] and rep["evaluated"] == [] and rep["insufficient"][0]["pipeline"] == "baseline"
    assert rep["recall_evaluated"] is False


def test_regression_ignores_warmup_errors_and_missing_metrics():
    rows = _rows(100, 300)
    for r in rows[:3]:
        r["warmup"] = 1
    for r in rows[3:6]:
        r["error"] = "boom"
    rep = ins.regression_alerts(rows, window=6)
    assert rep["insufficient"], "warm-up/erroring runs must not count towards the window"
    nometric = [dict(r, metrics={}) for r in _rows(100, 300)]
    assert ins.regression_alerts(nometric, window=6)["alerts"] == []


def test_alerts_endpoint_uses_settings_thresholds_and_query_wins(env):
    tc, db = env
    for r in [run(i, ctx=100) for i in range(6)] + [run(10 + i, ctx=125, created=2_000_000 + i) for i in range(6)]:
        db.save_run(r)
    assert tc.get("/api/alerts", params={"window": 6}).json()["alerts"][0]["change_pct"] == 25.0
    assert tc.put("/api/settings", json={"regression_thresholds": {"tokens_pct": 30}}).status_code == 200
    assert tc.get("/api/alerts", params={"window": 6}).json()["alerts"] == []        # 25% < stored 30%
    assert tc.get("/api/alerts", params={"window": 6, "tokens_pct": 10}).json()["alerts"]
    assert tc.put("/api/settings", json={"regression_thresholds": {"nope": 1}}).status_code == 422


def test_cli_fail_on_regression_flag_is_documented():
    out = subprocess.run([sys.executable, "-m", "memory_gateway", "benchmark", "--help"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60).stdout
    assert "--fail-on-regression" in out


# -- ANA-210 ---------------------------------------------------------------------------------------
def test_provider_health_error_rate_from_last_n():
    rows = ([run(i, provider="openai", lat=100.0 + i) for i in range(8)]
            + [run(20 + i, provider="openai", error="timeout") for i in range(2)]
            + [run(40 + i, provider="ollama") for i in range(3)] + [run(50, agent="hermes")])
    rows = [dict(r, metrics={"total_latency_ms": r["metrics_json"].get("total_latency_ms")}) for r in rows]
    h = ins.provider_health(rows, [{"agent": "codex", "available": False, "reason": "não instalado"}], last_n=100)
    by = {p["provider"]: p for p in h["providers"]}
    assert by["openai"]["calls"] == 10 and by["openai"]["errors"] == 2 and by["openai"]["error_rate"] == 0.2
    assert by["ollama"]["error_rate"] == 0.0 and by["agent:hermes"]["calls"] == 1
    assert by["openai"]["key_present"] is None and h["probe"] is False
    assert h["agents"] == [{"agent": "codex", "available": False, "metrics": None, "reason": "não instalado"}]
    assert ins.provider_health(rows, [], last_n=2)["providers"][0]["calls"] <= 2    # window is honoured


def test_providers_health_endpoint_reads_ledger_without_probe(env):
    tc, db = env
    db.save_run(run(1, provider="openai"))
    db.save_run(run(2, provider="openai", error="x"))
    d = tc.get("/api/providers/health?last_n=100").json()
    row = next(p for p in d["providers"] if p["provider"] == "openai")
    assert row["calls"] == 2 and row["error_rate"] == 0.5 and d["probe"] is False
    assert tc.get("/api/providers/health?last_n=0").status_code == 422


# -- ANA-213 ---------------------------------------------------------------------------------------
def test_lineage_links_note_origin_to_citing_runs(env):
    tc, db = env
    nid = tc.post("/api/memory/notes", json={"title": "Decisão pgbouncer", "content": "Usamos pgbouncer.", "project": "gw",
                                              "source_agent": "codex"}).json()["id"]
    note = tc.get(f"/api/memory/notes/{nid}").json()
    other = tc.post("/api/memory/notes", json={"title": "Sem origem", "content": "x"}).json()["id"]
    db.save_run(run(1, sources=[{"file": f"saved_context/{note['file']}", "tokens": 10}, {"file": "outra.md"}]))
    db.save_run(run(2, sources=[{"file": "outra.md"}]))
    d = tc.get("/api/memory/lineage").json()
    n = next(x for x in d["notes"] if x["id"] == nid)
    assert n["source_agent"] == "codex" and n["project"] == "gw" and n["has_origin"] is True
    assert n["cited_by_count"] == 1 and n["cited_by"][0]["run_id"] == "rbas1"
    o = next(x for x in d["notes"] if x["id"] == other)
    assert o["cited_by_count"] == 0 and o["source_agent"] is None and o["has_origin"] is False   # never inferred
    assert d["count"] == 2 and d["with_origin"] == 1 and d["origin_coverage"] == 0.5


def test_lineage_empty_store_has_no_coverage_number(env):
    tc, _ = env
    d = tc.get("/api/memory/lineage").json()
    assert d["count"] == 0 and d["origin_coverage"] is None


# -- ANA-208 ---------------------------------------------------------------------------------------
def test_preview_pipeline_validation_and_no_run(_gw_client):
    from app.api import memory_context, routes
    tc = _gw_client
    tc.app.include_router(memory_context.router)
    db = routes.gw().db
    before = db.query("SELECT COUNT(*) n FROM runs")[0]["n"]
    for pipe in ("baseline", "graphify"):
        d = tc.get("/api/memory/search-preview", params={"q": "driver asyncpg", "pipeline": pipe}).json()
        assert d["recorded"] is False and d["pipeline"] == pipe
    assert tc.get("/api/memory/search-preview", params={"q": "x", "pipeline": "graphify_jev"}).status_code == 422
    assert db.query("SELECT COUNT(*) n FROM runs")[0]["n"] == before


from tests.test_api_mcp import client as _gw_client  # noqa: E402,F401  (fixture)
