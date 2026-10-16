"""ANAM-012 (trace_id REST -> gateway -> db -> logs) e ANAM-019 (persistencia write-behind sem perder run)."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import request_context as rc
from app.core.state import STATE
from app.database.migrations import BENCHMARK_MIGRATIONS
from config.benchmark import BenchmarkConfig
from config.retrieval import RetrievalConfig

ROOT = Path(__file__).resolve().parents[1]
FIXED = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def _gw(tiny_vault, tmp_path, name="b.db", async_persist=True):
    from app.gateway.memory_gateway import MemoryGateway
    rcfg = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    bcfg = BenchmarkConfig(db_path=str(tmp_path / name), profile="benchmark")
    return MemoryGateway(retrieval_cfg=rcfg, bench_cfg=bcfg, async_persist=async_persist)


@pytest.fixture
def env(tiny_vault, tmp_path, monkeypatch):
    from app.api import routes
    from app.main import _install_trace_middleware
    from app.services.security import get_or_create_local_token
    gw = _gw(tiny_vault, tmp_path)
    app = FastAPI()
    _install_trace_middleware(app)
    app.include_router(routes.router)
    old = STATE.gateway
    STATE.gateway = gw
    tc = TestClient(app, client=("127.0.0.1", 51234), headers={"X-MG-Token": get_or_create_local_token()})
    try:
        yield type("E", (), {"client": tc, "gw": gw})
    finally:
        STATE.gateway = old
        gw.close()


Q = {"query": "stack backend FastAPI", "pipeline": "baseline"}


def test_rest_trace_id_crosses_gateway_db_and_log(env, caplog):
    log = logging.getLogger("memory_gateway")
    seen = []

    class Cap(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())
    h = Cap()
    h.addFilter(rc.TraceLogFilter())
    log.addHandler(h)
    try:
        r = env.client.post("/memory/search", json=Q, headers={"X-Trace-Id": FIXED})
        assert r.status_code == 200
        assert r.headers["X-Trace-Id"] == FIXED
        run_id = r.json()["run_id"]
        env.gw.log.info("probe dentro do request")           # fora do scope: sem prefixo
        with rc.request_scope(trace_id=FIXED):
            env.gw.log.info("probe com scope")
    finally:
        log.removeHandler(h)
    run = env.gw.db.get_run(run_id)                       # get_run enxerga a run (read-your-writes)
    assert run["metrics"]["trace_id"] == FIXED
    rows = env.gw.db.query("SELECT run_id FROM runs WHERE json_extract(metrics_json,'$.trace_id')=?", (FIXED,))
    assert [x["run_id"] for x in rows] == [run_id]
    assert any(m.startswith(f"[trace={FIXED}] probe com scope") for m in seen)
    assert "probe dentro do request" in seen              # sem scope aberto nao inventa trace


def test_rest_generates_trace_when_absent_and_ignores_unsafe(env):
    a = env.client.post("/memory/search", json=Q)
    assert len(a.headers["X-Trace-Id"]) == 32
    b = env.client.post("/memory/search", json=Q, headers={"X-Trace-Id": "x\r\ny"})
    assert b.headers["X-Trace-Id"] != "x\r\ny" and len(b.headers["X-Trace-Id"]) == 32
    assert a.headers["X-Trace-Id"] != b.headers["X-Trace-Id"]
    assert env.client.get("/health").headers.get("X-Trace-Id")


def test_direct_search_opens_own_trace_and_migration5_is_additive(tiny_vault, tmp_path):
    gw = _gw(tiny_vault, tmp_path)
    try:
        r = gw.search("backend FastAPI", "baseline", 3)
        tid = r.metrics["trace_id"]
        assert len(tid) == 32 and r.metrics["request_id"].startswith("req-")
        assert gw.db.get_run(r.run_id)["metrics"]["trace_id"] == tid
        assert rc.get_trace_id() is None                  # scope fechado ao sair
        assert gw.db.query("PRAGMA user_version")[0]["user_version"] == max(m.version for m in BENCHMARK_MIGRATIONS) >= 5
        cols = {x["name"] for x in gw.db.query("PRAGMA table_info(runs)")}
        assert "trace_id" not in cols                     # aditivo: nenhuma coluna nova/ruptura de schema
    finally:
        gw.close()


def test_mcp_search_carries_one_trace(tiny_vault, tmp_path, monkeypatch):
    from app.mcp import server
    gw = _gw(tiny_vault, tmp_path)
    monkeypatch.setattr(server, "_gateway", gw)
    monkeypatch.setattr(server, "BRIDGE_URL", "")
    try:
        with rc.request_scope(trace_id=FIXED):
            out = server._search("backend FastAPI", "baseline", 3)
        assert out
        row = gw.db.query("SELECT metrics_json FROM runs ORDER BY created_at DESC LIMIT 1")[0]
        assert json.loads(row["metrics_json"])["trace_id"] == FIXED
    finally:
        gw.close()


# -- ANAM-019 -----------------------------------------------------------------------------------
def test_async_persist_get_run_semantics_and_jsonl(tiny_vault, tmp_path, monkeypatch):
    import app.gateway.memory_gateway as mg
    lines = []
    monkeypatch.setattr(mg, "jsonl", lambda stream, rec: lines.append((stream, rec)))
    gw = _gw(tiny_vault, tmp_path)
    assert gw._bench_log is not None and gw.db._writer is not None   # default = write-behind
    try:
        ids = [gw.search("backend FastAPI", "baseline", 3).run_id for _ in range(15)]
        for rid in ids:                                    # sem flush explicito: get_run ja devolve
            run = gw.db.get_run(rid)
            assert run and run["context"] is not None and run["candidates"]
        assert gw.flush_persistence()
        assert [r["run_id"] for s, r in lines if s == "benchmark"] == ids   # ordem preservada
    finally:
        gw.close()


def test_sync_fallback_env(tiny_vault, tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_GATEWAY_ASYNC_PERSIST", "0")
    gw = _gw(tiny_vault, tmp_path)
    try:
        assert gw._bench_log is None and gw.db._writer is None
        rid = gw.search("backend FastAPI", "baseline", 3).run_id
        assert gw.db.get_run(rid)["run_id"] == rid
    finally:
        gw.close()


def test_default_is_sync_and_opt_in_is_async(tiny_vault, tmp_path, monkeypatch):
    monkeypatch.delenv("ANAMNESIA_GATEWAY_ASYNC_PERSIST", raising=False)
    a = _gw(tiny_vault, tmp_path, "a.db", async_persist=None)
    b = _gw(tiny_vault, tmp_path, "b2.db", async_persist=True)
    try:
        assert a._bench_log is None and a.db._writer is None
        assert b._bench_log is not None and b.db._writer is not None
    finally:
        a.close()
        b.close()


def test_shutdown_without_close_does_not_lose_confirmed_runs(tiny_vault, tmp_path):
    """Processo filho faz N search() e sai SEM close()/flush: atexit tem que gravar tudo (db + jsonl)."""
    code = f"""
import os, sys, json
sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from config.benchmark import BenchmarkConfig
from config.retrieval import RetrievalConfig
from app.gateway.memory_gateway import MemoryGateway
gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=Path({str(tiny_vault)!r}), data_dir=Path({str(tmp_path / 'd2')!r})),
                   bench_cfg=BenchmarkConfig(db_path={str(tmp_path / 'child.db')!r}, profile="benchmark"), async_persist=True)
ids = [gw.search("backend FastAPI", "baseline", 3).run_id for _ in range(25)]
print(json.dumps(ids))
"""
    env = {**__import__("os").environ, "ANAMNESIA_HOME": str(tmp_path / "home")}
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    ids = json.loads(p.stdout.strip().splitlines()[-1])
    import sqlite3
    con = sqlite3.connect(tmp_path / "child.db")
    got = {r[0] for r in con.execute("SELECT run_id FROM runs")}
    con.close()
    assert set(ids) <= got and len(ids) == 25
    jl = tmp_path / "home" / "logs" / "benchmark.jsonl"
    if jl.exists():
        logged = {json.loads(x)["run_id"] for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()}
        assert set(ids) <= logged


def test_persist_queue_backpressure_flushes(tiny_vault, tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PERSIST_MAX_QUEUE", "2")
    gw = _gw(tiny_vault, tmp_path)
    try:
        ids = [gw.search("backend FastAPI", "baseline", 3).run_id for _ in range(12)]
        assert gw.flush_persistence()
        assert len(gw.db.query("SELECT run_id FROM runs")) == len(set(ids)) == 12
    finally:
        gw.close()
