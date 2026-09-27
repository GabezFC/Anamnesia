"""REST API (FastAPI TestClient) and MCP tool schema tests. No network, no graphify, no TypeSafe."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.models import Candidate
from app.services.obsidian import split_sections
from config.benchmark import BenchmarkConfig
from config.jev import JevConfig
from config.retrieval import RetrievalConfig


class FakeJevBackend:
    def evaluate(self, state, questions):
        answers = {}
        for name, q in questions.items():
            src = q["instructions"]["candidate"]["source"]
            if name.startswith("rel_"):
                answers[name] = 0.1 if "viagem" in src else 0.9
            else:
                answers[name] = 0.0
        return answers, {"input_tokens": 50, "output_tokens": 5}, "jev-1.13.0"


class FakeGraphify:
    def __init__(self, vault_root, mirror):
        self.vault_root = vault_root
        self.graph_path = mirror / "graphify-out" / "graph.json"

    def search(self, query, limit=100):
        cands = []
        files = sorted(p for p in self.vault_root.rglob("*.md") if ".obsidian" not in p.parts)
        for i, p in enumerate(files[:limit]):
            rel = p.relative_to(self.vault_root).as_posix()
            sec = split_sections(p.read_text(encoding="utf-8"))[0]
            cands.append(Candidate(candidate_id=f"g{i:03d}:{rel}#L{sec.line}", source_file=rel,
                                   section=sec.heading_path, snippet=sec.text, score=1.0 - i * 0.1,
                                   origin="graphify"))
        return cands, {"graphify_nodes_returned": len(cands)}

    def build(self):
        return {"files": 0}

    def version(self):
        return "fake-graphify 0.0"


@pytest.fixture
def client(tiny_vault, tmp_path):
    from app.api import routes
    from app.gateway.memory_gateway import MemoryGateway

    rcfg = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    bcfg = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark")
    jcfg = JevConfig(model="jev-1.13.0", mode="performance", relevance_threshold=0.78, review_threshold=0.55,
                     injection_threshold=0.80, review_action="keep", failure_mode="fail_open", second_pass=False)
    gw = MemoryGateway(retrieval_cfg=rcfg, jev_cfg=jcfg, bench_cfg=bcfg, jev_backend=FakeJevBackend(),
                       graphify_service=FakeGraphify(tiny_vault, rcfg.mirror_dir))
    app = FastAPI()
    app.include_router(routes.router)
    old = routes._state["gateway"]
    routes._state["gateway"] = gw
    try:
        yield TestClient(app)
    finally:
        routes._state["gateway"] = old
        gw.db.conn.close() if hasattr(gw.db, "conn") else None


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "vault_exists": True}


@pytest.mark.parametrize("pipeline", ["baseline", "graphify", "graphify_jev"])
def test_memory_search_pipelines(client, pipeline):
    r = client.post("/memory/search", json={"query": "stack backend FastAPI", "pipeline": pipeline})
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("query", "pipeline", "context", "sources", "metrics"):
        assert k in body
    assert body["pipeline"] == pipeline
    assert body["query"] == "stack backend FastAPI"
    assert "error" not in body["metrics"], body["metrics"].get("error")
    assert body["sources"]
    assert body["context"]


def test_graphify_jev_filters_irrelevant(client):
    body = client.post("/memory/search", json={"query": "stack", "pipeline": "graphify_jev"}).json()
    files = {s["file"] for s in body["sources"]}
    assert "50-Pessoal/viagem-ferias.md" not in files
    assert body["metrics"]["jev_input_tokens"] == 50


def test_invalid_pipeline_422(client):
    r = client.post("/memory/search", json={"query": "x", "pipeline": "nope"})
    assert r.status_code == 422


def test_get_run_after_search(client):
    body = client.post("/memory/search", json={"query": "stack", "pipeline": "baseline"}).json()
    run_id = body["run_id"]
    r = client.get(f"/benchmark/runs/{run_id}")
    assert r.status_code == 200
    assert r.json()["run_id"] == run_id
    assert client.get("/benchmark/runs/doesnotexist").status_code == 404


def test_false_negative_feedback(client):
    body = client.post("/memory/search", json={"query": "stack", "pipeline": "graphify_jev",
                                                "include_candidates": True}).json()
    run = client.get(f"/benchmark/runs/{body['run_id']}").json()
    dropped = [c for c in run["candidates"] if c["decision"] == "DROP"]
    assert dropped, "expected the viagem note to be dropped and stored"
    cid = dropped[0]["candidate_id"]
    r = client.post("/feedback/false-negative", json={"run_id": body["run_id"], "candidate_id": cid})
    assert r.status_code == 200, r.text
    assert r.json()["candidate_id"] == cid
    assert r.json()["jev_score"] == pytest.approx(0.1)
    bad = client.post("/feedback/false-negative", json={"run_id": body["run_id"], "candidate_id": "nope"})
    assert bad.status_code == 404


# -- MCP ------------------------------------------------------------------------
EXPECTED_TOOLS = {"memory_search", "memory_search_baseline", "memory_search_graphify",
                  "memory_search_graphify_jev", "memory_benchmark", "memory_get_run", "memory_stats"}


def _schema(tool):
    for attr in ("inputSchema", "input_schema"):
        s = getattr(tool, attr, None)
        if s is not None:
            return s
    raise AssertionError(f"tool {tool} has no input schema")


def test_mcp_tools_schema():
    from app.mcp import server as mod
    tools = asyncio.run(mod.server.list_tools())
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    for t in tools:
        s = _schema(t)
        assert isinstance(s, dict) and s.get("type") == "object"
        for bad in ("write", "delete", "rename", "move"):
            assert bad not in t.name
    by_name = {t.name: _schema(t) for t in tools}
    for n in ("memory_search", "memory_search_baseline", "memory_search_graphify", "memory_search_graphify_jev"):
        assert "query" in by_name[n].get("required", [])
    assert "run_id" in by_name["memory_get_run"].get("required", [])
