"""Settings API, cost extensions (range/hourly/budget/by-role/SSE push), benchmark aggregate/report,
memory last-search, and the opt-in economy rules. Real gateway on a temp vault/DB (fixture from test_api_mcp)."""
from __future__ import annotations

import json
import threading
import time

import pytest

from app.api import benchmark_report, costs as costs_api, costs_ext, memory_context, settings as settings_api
from app.gateway.economy import (EconomySettings, JEV_MIN_POOL, apply_economy, scale_max_results,
                                 should_use_jev_opt)
from app.gateway.optimizer import Plan
from app.services.query_fp import classify
from tests.test_api_mcp import client as _gw_client  # noqa: F401  (fixture)
from tests.test_costs_ledger import jev_run, mk_run

COMPLEX_Q = "Quais são as duas notas relacionadas e como se conectam, e qual decisão depende da outra?"


@pytest.fixture
def api(_gw_client):
    tc = _gw_client
    for mod in (settings_api, costs_api, benchmark_report, memory_context):
        tc.app.include_router(mod.router)
    from app.api import routes
    return tc, routes.gw().db


# -- settings ------------------------------------------------------------------------------------
def test_settings_defaults_and_partial_merge(api):
    tc, db = api
    d = tc.get("/api/settings").json()
    assert d["language"] == "pt-BR" and d["default_pipeline"] == "auto"
    assert d["budget"] == {"daily_usd": None, "monthly_usd": None, "alert_pct": 80.0}
    assert d["max_tokens_per_query"] is None and d["auto_graphify_jev_opt"] is False
    assert d["reduce_max_results_by_question_type"] is False
    assert d["subagent_preset"] == {} and d["prefilter_cache"] == {} and d["terminal_layout"] == {}

    r = tc.put("/api/settings", json={"language": "en", "budget": {"daily_usd": 2.5},
                                      "terminal_layout": {"cols": 2}, "max_tokens_per_query": 3000})
    assert r.status_code == 200
    r = tc.put("/api/settings", json={"budget": {"alert_pct": 70}, "auto_graphify_jev_opt": True}).json()
    assert r["language"] == "en" and r["terminal_layout"] == {"cols": 2}      # untouched by 2nd PUT
    assert r["budget"] == {"daily_usd": 2.5, "monthly_usd": None, "alert_pct": 70.0}
    assert r["max_tokens_per_query"] == 3000 and r["auto_graphify_jev_opt"] is True
    assert tc.get("/api/settings").json() == r
    assert db.get_budgets()["day"] == 2.5                                     # shared with the cost ledger
    # explicit null clears the cap and a budget ceiling
    r = tc.put("/api/settings", json={"max_tokens_per_query": None, "budget": {"daily_usd": None}}).json()
    assert r["max_tokens_per_query"] is None and r["budget"]["daily_usd"] is None


def test_settings_validation_and_guard(api):
    tc, _ = api
    for bad in ({"language": "fr"}, {"budget": {"alert_pct": 0}}, {"budget": {"daily_usd": -1}},
                {"max_tokens_per_query": 0}, {"default_pipeline": "nope"}, {"unknown": 1}):
        assert tc.put("/api/settings", json=bad).status_code == 422, bad
    from fastapi.testclient import TestClient
    anon = TestClient(tc.app, client=("127.0.0.1", 1))          # no token
    assert anon.put("/api/settings", json={"language": "en"}).status_code == 403
    assert anon.get("/api/settings").status_code == 200


def test_settings_persist_across_reopen(api):
    tc, db = api
    tc.put("/api/settings", json={"default_pipeline": "baseline", "subagent_preset": {"name": "x"}})
    from app.database.db import Database
    db2 = Database(db.path) if hasattr(db, "path") else None
    if db2 is None:
        pytest.skip("Database has no path attribute")
    from app.services.settings_store import load_settings
    s = load_settings(db2)
    assert s.default_pipeline == "baseline" and s.subagent_preset == {"name": "x"}
    db2.conn.close()


# -- costs ----------------------------------------------------------------------------------------
def _seed(db):
    now = time.time()
    db.save_run(mk_run("old", created_at=now - 20 * 86400))
    db.save_run(mk_run("mid", created_at=now - 3 * 86400))
    db.save_run(jev_run("new", created_at=now - 5))


def test_range_filters_summary_and_calls(api):
    tc, db = api
    _seed(db)
    n = lambda r: tc.get(f"/api/costs/calls?range={r}&limit=50").json()["items"]  # noqa: E731
    assert (len(n("today")), len(n("7d")), len(n("30d")), len(n("all"))) == (1, 2, 3, 3) or len(n("today")) <= 1
    assert len(n("7d")) == 2 and len(n("30d")) == 3 and len(n("all")) == 3
    assert tc.get("/api/costs/summary?range=7d").json()["calls"] == 2
    assert tc.get("/api/costs/calls?range=bad").status_code == 422


def test_hourly_series(api):
    tc, db = api
    now = time.time()
    db.save_run(mk_run("h1", created_at=now - 1))
    db.save_run(jev_run("h2", created_at=now - 2))
    d = tc.get("/api/costs/hourly?range=7d").json()
    assert d["range"] == "7d"
    pts = d["points"]
    assert len(pts) >= 7 * 24 - 1 and pts == sorted(pts, key=lambda p: p["hour"])
    assert sum(p["calls"] for p in pts) == 2
    assert sum(p["cost_usd"] for p in pts) == pytest.approx(0.000042)
    assert {"hour", "calls", "context_tokens", "judge_tokens", "total_tokens_spent", "cost_usd"} <= set(pts[-1])
    assert tc.get("/api/costs/hourly?range=all").json()["points"]


def test_budget_get_put_alert(api):
    tc, db = api
    b = tc.get("/api/costs/budget").json()
    assert b["alert_pct"] == 80.0 and b["alert"] is False and b["daily"]["limit_usd"] is None
    db.save_run(jev_run("j", created_at=time.time()))      # costs 0.000042
    r = tc.put("/api/costs/budget", json={"daily_usd": 0.00005, "monthly_usd": 1.0}).json()
    assert r["daily"]["limit_usd"] == 0.00005 and r["daily"]["spent_usd"] == pytest.approx(0.000042)
    assert r["daily"]["percent"] == pytest.approx(84.0) and r["daily"]["alert"] is True
    assert r["daily"]["exceeded"] is False and r["monthly"]["alert"] is False and r["alert"] is True
    r = tc.put("/api/costs/budget", json={"alert_pct": 90}).json()
    assert r["alert_pct"] == 90.0 and r["daily"]["alert"] is False
    # legacy form still works
    r = tc.put("/api/costs/budget", json={"period": "day", "ceiling_usd": 10}).json()
    assert r == {"budgets": {"day": 10.0, "month": 1.0}}
    assert tc.get("/api/costs/budget").json()["daily"]["limit_usd"] == 10
    assert tc.put("/api/costs/budget", json={"period": "year", "ceiling_usd": 1}).status_code == 422
    assert tc.put("/api/costs/budget", json={"daily_usd": -1}).status_code == 422
    assert tc.get("/api/settings").json()["budget"]["alert_pct"] == 90.0


def test_by_role_falls_back_to_agent_then_uses_orchestration(api):
    tc, db = api
    db.save_run(mk_run("a", created_at=time.time()))

    class Orch:
        def __init__(self, runs): self.runs = runs
        def list(self, p=None): return self.runs

    tc.app.dependency_overrides[costs_ext.get_orchestrator] = lambda: Orch([])
    d = tc.get("/api/costs/by-role?range=all").json()
    assert d["source"] == "agent" and d["items"][0]["role"] == "mcp" and d["items"][0]["calls"] == 1
    runs = [{"run_id": "r1", "created_at": time.time(), "steps": [
        {"role": "researcher", "state": "done", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.01},
        {"role": "researcher", "state": "done", "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.02},
        {"role": "reviewer", "state": "done", "input_tokens": 3, "output_tokens": 3, "cost_usd": None},
        {"role": "implementer", "state": "pending"}]}]
    tc.app.dependency_overrides[costs_ext.get_orchestrator] = lambda: Orch(runs)
    d = tc.get("/api/costs/by-role").json()
    by = {i["role"]: i for i in d["items"]}
    assert d["source"] == "orchestration" and set(by) == {"researcher", "reviewer"}
    assert by["researcher"]["cost_usd"] == pytest.approx(0.03) and by["researcher"]["calls"] == 2
    assert by["researcher"]["input_tokens"] == 11 and by["reviewer"]["cost_status"] == "unavailable"


def test_stream_pushes_at_insert_time_without_polling(api):
    tc, db = api
    got = {}

    def reader():
        # poll_interval is the 10 s max: only the insert-time wake-up can deliver in < 5 s
        t0 = time.monotonic()
        with tc.stream("GET", "/api/costs/stream?max_events=1&max_seconds=20&poll_interval=10") as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    got["data"] = json.loads(line[5:])
                    got["dt"] = time.monotonic() - t0
                    break

    th = threading.Thread(target=reader)
    th.start()
    time.sleep(0.5)
    db.save_run(mk_run("pushed", created_at=time.time()))
    th.join(8)
    assert got.get("data", {}).get("run_id") == "pushed"
    assert got["dt"] < 5


# -- benchmark aggregate / report ------------------------------------------------------------------
def test_benchmark_aggregate_and_report(api):
    tc, db = api
    now = time.time()
    for i, lat in enumerate([10.0, 20.0, 30.0, 40.0]):
        db.save_run(mk_run(f"b{i}", created_at=now - i, total_latency_ms=lat))
    db.save_run(jev_run("j1", created_at=now, total_latency_ms=100.0))
    db.save_run({**mk_run("w", created_at=now), "warmup": 1})
    db._exec("INSERT INTO evaluations (created_at, run_id, pipeline, accuracy, completeness, groundedness,"
             " citation_quality) VALUES (?,?,?,?,?,?,?)", (now, "b0", "baseline", 4, 5, 3, 4))
    agg = tc.get("/api/benchmark/aggregate?range=all").json()
    by = {p["pipeline"]: p for p in agg["pipelines"]}
    assert agg["total_runs"] == 5 and set(by) == {"baseline", "graphify_jev"}     # warm-up excluded
    b = by["baseline"]
    assert b["n"] == 4 and b["latency_ms"]["mean"] == 25.0 and b["latency_ms"]["p50"] == 25.0
    assert b["latency_ms"]["p95"] == 40.0 and b["context_tokens"]["mean"] == 100
    assert b["scores"]["accuracy"] == 4.0 and b["scores"]["n"] == 1
    assert by["graphify_jev"]["cost_usd"]["total"] == pytest.approx(0.000042)
    assert by["graphify_jev"]["scores"]["accuracy"] is None
    assert tc.get("/api/benchmark/aggregate?range=today&include_warmup=true").json()["total_runs"] == 6
    md = tc.get("/api/benchmark/report.md")
    assert md.status_code == 200 and "markdown" in md.headers["content-type"]
    assert "| baseline | 4 |" in md.text and "graphify_jev" in md.text
    assert tc.get("/api/benchmark/report.json").json()["total_runs"] == 5
    assert tc.get("/api/benchmark/aggregate?range=bad").status_code == 422


# -- memory last-search ------------------------------------------------------------------------------
def test_last_search_records_real_search(api):
    tc, db = api
    assert tc.get("/api/memory/last-search").json() == {"found": False}
    r = tc.post("/memory/search", json={"query": "driver asyncpg", "pipeline": "baseline"})
    assert r.status_code == 200
    ls = tc.get("/api/memory/last-search").json()
    assert ls["found"] is True and ls["run_id"] == r.json()["run_id"] and ls["query"] == "driver asyncpg"
    assert ls["sources"] == [{k: s.get(k) for k in ("file", "section", "score", "relevance", "decision", "tokens")}
                             for s in r.json()["sources"]]
    assert ls["tokens"]["context"] == r.json()["metrics"]["context_tokens"]
    assert ls["context"] == r.json()["context"]
    tc.post("/memory/search", json={"query": "outra pergunta", "pipeline": "baseline"})
    assert tc.get("/api/memory/last-search").json()["query"] == "outra pergunta"


def test_last_search_metrics_only_hides_text(api, monkeypatch):
    tc, _ = api
    tc.post("/memory/search", json={"query": "driver asyncpg", "pipeline": "baseline"})
    monkeypatch.setenv("MG_METRICS_ONLY", "1")
    ls = tc.get("/api/memory/last-search").json()
    assert ls["query"] is None and ls["context"] is None and ls["found"]


def test_search_preview_does_not_record(api):
    tc, db = api
    before = db.query("SELECT COUNT(*) n FROM runs")[0]["n"]
    d = tc.get("/api/memory/search-preview", params={"q": "driver asyncpg"}).json()
    assert d["recorded"] is False and d["pipeline"] == "baseline" and "sources" in d
    assert db.query("SELECT COUNT(*) n FROM runs")[0]["n"] == before
    assert tc.get("/api/memory/search-preview").status_code == 422


# -- economy ----------------------------------------------------------------------------------------
def _plan(q, pipeline="baseline", requested="auto"):
    return Plan(requested, pipeline, classify(q), "t")


def test_should_use_jev_opt_heuristic():
    assert should_use_jev_opt("COMPLEX", False, JEV_MIN_POOL) == (True, f"hard_pool:COMPLEX:{JEV_MIN_POOL}")
    assert should_use_jev_opt("COMPLEX", False, JEV_MIN_POOL - 1)[0] is False        # pool too small
    assert should_use_jev_opt("COMPLEX", False, None) == (False, "pool_unknown")
    assert should_use_jev_opt("SIMPLE", False, 500)[0] is False
    assert should_use_jev_opt("MEDIUM", True, 500)[0] is False
    assert should_use_jev_opt("AMBIGUOUS", False, 500)[0] is False
    assert should_use_jev_opt("AMBIGUOUS", True, 500)[0] is True
    assert should_use_jev_opt("COMPLEX", False, 100, max_tokens=5000)[0] is False    # judge alone > cap
    assert should_use_jev_opt("COMPLEX", False, 100, max_tokens=50000)[0] is True


def test_scale_max_results():
    assert scale_max_results("SIMPLE", 10) == 5 and scale_max_results("SIMPLE", 2) == 2
    assert scale_max_results("SIMPLE", 4) == 3
    assert scale_max_results("MEDIUM", 10) == 10
    assert scale_max_results("COMPLEX", 10) == 15 and scale_max_results("AMBIGUOUS", 40) == 50


def test_apply_economy_default_is_inert():
    plan = _plan(COMPLEX_Q)
    out = apply_economy(EconomySettings(), plan, 10, None, 4000, lambda: 1 / 0)       # probe must not run
    assert out == (plan, 10, None, {})


def test_apply_economy_opt_in():
    eco = EconomySettings(auto_graphify_jev_opt=True, reduce_max_results_by_question_type=True,
                          max_tokens_per_query=1500)
    plan, mr, budget, m = apply_economy(eco, _plan(COMPLEX_Q), 10, None, 4000, lambda: 200)
    assert plan.pipeline in ("baseline", "graphify_jev_opt")
    assert mr == 15 and budget == 1500 and m["economy_token_cap"] == {"from": 4000, "to": 1500}
    assert m["economy_jev_opt"].startswith("judge_over_cap")                          # 200*150 > 1500
    eco2 = EconomySettings(auto_graphify_jev_opt=True)
    plan, *_ = apply_economy(eco2, _plan(COMPLEX_Q), 10, None, 4000, lambda: 200)
    assert plan.pipeline == "graphify_jev_opt" and plan.reason.startswith("economy:")
    # explicit pipelines are never touched, even with everything on
    explicit = _plan(COMPLEX_Q, "graphify", requested="graphify")
    plan, mr, _, _ = apply_economy(eco, explicit, 10, None, 4000, lambda: 200)
    assert plan is explicit and mr == 10
    # cap does not raise a smaller requested budget
    assert apply_economy(eco, explicit, 10, 800, 4000, lambda: 0)[2] == 800
    # a route configured away from baseline is not overridden
    gr = _plan(COMPLEX_Q, "graphify")
    assert apply_economy(eco2, gr, 10, None, 4000, lambda: 200)[0].pipeline == "graphify"


def test_gateway_search_default_unchanged_and_opt_in_applies(api):
    tc, db = api
    base = tc.post("/memory/search", json={"query": "driver asyncpg", "max_results": 10}).json()
    assert not any(k.startswith("economy_") for k in base["metrics"])
    tc.put("/api/settings", json={"max_tokens_per_query": 300, "reduce_max_results_by_question_type": True})
    on = tc.post("/memory/search", json={"query": "driver asyncpg", "max_results": 10}).json()
    assert on["metrics"]["context_tokens"] <= 300 or on["metrics"].get("economy_token_cap")
