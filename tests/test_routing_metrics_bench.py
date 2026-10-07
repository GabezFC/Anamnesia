"""R5/R6: routing metrics (hand-computed), oracle/regret, break-even, harness, report, db migration, endpoint."""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import costs as costs_api
from app.api import costs_routing
from app.benchmark import routing_bench as rb
from app.database.db import Database
from app.routing import metrics as M
from app.routing.registry import ModelEntry, Price
from app.routing.tasks import load_tasks


def rec(tid, strat="S", solved=True, cost=1.0, diff="easy", kind="extraction", **kw):
    r = {"task_id": tid, "strategy": strat, "solved": solved, "cost": cost, "final_cost": cost, "cost_origin": "measured",
         "tokens": 100, "difficulty": diff, "kind": kind, "router_cost": 0.0, "verify_cost": 0.0, "retry_cost": 0.0,
         "escalation_count": 0, "retry_count": 0, "simulated": False, "initial_tier": 1, "t_star": None}
    r.update(kw)
    return r


# ---------------------------------------------------------------- formulas
def test_cost_per_solved_and_tokens():
    rs = [rec("a", cost=2.0), rec("b", cost=4.0, solved=False), rec("c", cost=3.0)]
    assert M.total_cost(rs)["value"] == 9.0
    assert M.cost_per_solved_task(rs) == {"value": 4.5, "origin": "measured"}      # 9 / 2 solved
    assert M.tokens_per_solved_task(rs)["value"] == 150.0                           # 300 / 2


def test_null_price_never_becomes_zero():
    rs = [rec("a", cost=2.0), rec("b", cost=None)]
    assert M.cost_per_solved_task(rs) == {"value": None, "origin": "unavailable"}
    assert M.total_cost(rs)["value"] is None
    assert M.cost_per_solved_task([rec("a", solved=False)])["value"] is None       # nobody solved


def test_escalation_and_retry_rate():
    rs = [rec("a", escalation_count=1), rec("b"), rec("c", escalation_count=2), rec("d", retry_count=1)]
    assert M.escalation_rate(rs)["value"] == 0.5
    assert M.retry_rate(rs)["value"] == 0.25
    assert M.retry_rate([rec("a", retry_count=None)])["value"] is None


def test_oracle_t_star_and_regret():
    cells = {"cheap": {"tier": 1, "solved": False, "cost": 1.0}, "mid": {"tier": 2, "solved": True, "cost": 3.0},
             "top": {"tier": 3, "solved": True, "cost": 10.0}}
    o = M.oracle_for_task(cells)
    assert (o["t_star"], o["model"], o["cost"]) == (2, "mid", 3.0)
    assert M.oracle_for_task({"x": {"tier": 1, "solved": False, "cost": 1.0}}) is None
    # solved with top: regret = 10 - 3; failed with cheap: 1 + penalty(10) - 3
    r1 = rec("a", cost=10.0, t_star=2, oracle_cost=3.0, penalty_cost=10.0, difficulty="easy")
    r2 = rec("b", cost=1.0, solved=False, t_star=2, oracle_cost=3.0, penalty_cost=10.0, difficulty="hard")
    assert M.task_regret(r1) == 7.0 and M.task_regret(r2) == 8.0
    g = M.regret([r1, r2])
    assert g["total"]["value"] == 15.0 and g["mean"]["value"] == 7.5
    assert g["mean_by_difficulty"]["easy"]["value"] == 7.0 and g["mean_by_difficulty"]["medium"]["value"] is None
    assert M.regret([dict(r1, oracle_cost=None)])["total"]["value"] is None


def test_over_under_routing():
    rs = [rec("a", initial_tier=3, t_star=1), rec("b", initial_tier=1, t_star=2, solved=False),
          rec("c", initial_tier=2, t_star=2), rec("d", initial_tier=2, t_star=None),
          rec("e", initial_tier=3, t_star=1, solved=False)]            # failed with higher tier: not "over"
    c = M.routing_classification(rs)
    assert (c["over_routed"], c["under_routed"], c["exact"], c["no_tstar"]) == (1, 1, 2, 1)
    assert c["judged"] == 4 and c["over_rate"]["value"] == 0.25


def test_break_even_positive_and_negative():
    base = [rec("a", "B", cost=10.0), rec("b", "B", cost=10.0)]
    # dynamic: cheaper models (final 3 each) + overheads 1 router + 0.5 verify + 1 retry per task
    dyn = [rec(t, "D", cost=3 + 1.5, final_cost=3.0, router_cost=0.5, verify_cost=0.5, retry_cost=0.5) for t in "ab"]
    be = M.break_even(dyn, base)
    assert be["model_savings"]["value"] == 14.0 and be["routing_overhead"]["value"] == 1.0
    assert be["verification_overhead"]["value"] == 1.0 and be["retry_overhead"]["value"] == 1.0
    assert be["net_savings"]["value"] == 11.0 and be["pays_for_itself"] is True
    assert M.verdict(be)["value"] == "SIM"
    # overheads above savings -> NÃO
    bad = [rec(t, "D", cost=9.0, final_cost=9.5, router_cost=3.0, verify_cost=2.0, retry_cost=3.0) for t in "ab"]
    be2 = M.break_even(bad, base)
    assert be2["model_savings"]["value"] == 1.0 and be2["net_savings"]["value"] == 1.0 - 16.0   # 20 - 19 ; 16 overhead
    assert be2["pays_for_itself"] is False and M.verdict(be2)["value"] == "NÃO"
    # unavailable price -> sem dados, never SIM
    be3 = M.break_even([rec("a", "D", cost=None, final_cost=None)], [rec("a", "B", cost=1.0)])
    assert be3["pays_for_itself"] is None and M.verdict(be3)["value"] == "sem dados"
    # saves money but quality dropped -> NÃO
    q = M.break_even([rec("a", "D", cost=1.0, solved=False)], [rec("a", "B", cost=5.0)])
    assert q["pays_for_itself"] and M.verdict(q)["value"] == "NÃO"


def test_per_difficulty_breakdown():
    rs = [rec("a", diff="easy", cost=1.0), rec("b", diff="hard", cost=6.0), rec("c", diff="hard", cost=2.0, solved=False)]
    b = M.by_difficulty(rs)
    assert b["easy"]["cost_per_solved_task"]["value"] == 1.0
    assert b["hard"]["cost_per_solved_task"]["value"] == 8.0 and b["hard"]["n"] == 2
    assert b["medium"]["n"] == 0 and b["medium"]["success_rate"]["value"] is None


def test_summary_ignores_simulated():
    s = M.build_summary([rec("a", simulated=True)])
    assert s["has_data"] is False and s["verdict"]["value"] == "sem dados" and s["simulated_only"]
    assert M.build_summary([])["verdict"]["value"] == "sem dados"


# ---------------------------------------------------------------- harness
def priced_models():
    mk = lambda i, t, p, loc=False: ModelEntry(i, "openai", i, t, 8000, (), False, p, loc)  # noqa: E731
    return [mk("m1", 1, Price(1.0, 2.0, "u", "2026-01-01")), mk("m2", 2, Price(3.0, 6.0, "u", "2026-01-01")),
            mk("m3", 3, Price(10.0, 20.0, "u", "2026-01-01"))]


@pytest.fixture(scope="module")
def tasks():
    return rb.sample_tasks(load_tasks(), 24, 7)


def test_cache_runs_each_task_model_once(tasks):
    runner = rb.StubRunner()
    cache = rb.ResultCache()
    res = rb.run_benchmark(tasks, priced_models(), runner, rb.ALL_STRATEGIES, ("balanced", "economic"), None, cache)
    assert runner.calls == cache.executions <= len(tasks) * 3
    assert cache.hits > 0
    assert len(cache.cells) == cache.executions
    assert {r["strategy"] for r in res.records} >= set(rb.ALL_STRATEGIES)


def test_stub_benchmark_deterministic(tasks):
    a = rb.run_benchmark(tasks, priced_models(), rb.StubRunner(3))
    b = rb.run_benchmark(tasks, priced_models(), rb.StubRunner(3))
    strip = lambda rs: json.dumps([{k: v for k, v in r.items() if k != "router_latency_ms"} for r in rs],  # noqa: E731
                                  sort_keys=True, default=str)   # wall-clock router latency is real, not simulated
    assert strip(a.records) == strip(b.records)
    assert all(r["simulated"] for r in a.records)


def test_oracle_is_cheapest_and_never_worse(tasks):
    res = rb.run_benchmark(tasks, priced_models(), rb.StubRunner())
    by = {}
    for r in res.records:
        by.setdefault(r["strategy"], {})[r["task_id"]] = r
    for tid, o in by["ORACLE"].items():
        for s in ("STATIC_CHEAP", "STATIC_DEFAULT", "STATIC_STRONG"):
            st = by[s][tid]
            if st["solved"]:
                assert o["solved"] and o["cost"] <= st["cost"] + 1e-12
        assert o["t_star"] is None or o["t_star"] >= 1


def test_dynamic_escalates_with_chain_and_tracks_cost(tasks):
    res = rb.run_benchmark(tasks, priced_models(), rb.StubRunner(), [rb.DYNAMIC_ROUTER])
    for r in res.records:
        assert 0 <= r["escalation_count"] <= 2
        assert r["cost"] >= r["final_cost"] - 1e-12
        if r["escalation_count"]:
            assert r["final_tier"] > r["initial_tier"]


def test_unpriced_cloud_model_gives_null_cost(tasks):
    models = [ModelEntry("c1", "openai", "c1", 1, 8000), ModelEntry("c2", "openai", "c2", 2, 8000)]
    res = rb.run_benchmark(tasks[:6], models, rb.StubRunner(), [rb.STATIC_CHEAP])
    assert all(r["cost"] is None and r["cost_origin"] == "unavailable" for r in res.records)


def test_report_refuses_claims_without_data(tasks):
    res = rb.run_benchmark(tasks, priced_models(), rb.StubRunner())
    md = rb.render_report(res, "2026-01-01", real_mode=False)
    assert "SIMULATED (stub runner): numbers are NOT evidence" in md
    qa = rb.answer_questions(res.records)
    assert len(qa) == 12 and all(a.startswith("sem dados") for _, a in qa)
    assert "SIM:" not in md and "economia líquida" not in md.split("## Limitações")[0].split("## As 12")[1].split("## Mecânica")[0]


def test_questions_answered_when_real_records_exist():
    base = [rec(t, "STATIC_DEFAULT", cost=10.0, final_cost=10.0, tokens=100, diff="easy") for t in "abc"]
    dyn = [rec(t, "DYNAMIC_ROUTER", cost=4.0, final_cost=4.0, tokens=50, diff="easy", router_latency_ms=0.1,
               initial_tier=1, t_star=1) for t in "abc"]
    qa = dict(rb.answer_questions(base + dyn))
    assert qa["O Dynamic Router economizou dinheiro?"].startswith("SIM")
    assert "50.0% de redução" in qa["O Dynamic Router economizou tokens?"]
    assert qa["Quantas tarefas precisaram de escalation?"].startswith("0 de 3")
    assert qa["Qual política/threshold apresentou melhor resultado?"].startswith("sem dados")


# ---------------------------------------------------------------- db
OLD_SCHEMA = ("CREATE TABLE runs (run_id TEXT PRIMARY KEY, session_id TEXT, created_at REAL, question_id TEXT, query TEXT,"
              " pipeline TEXT, agent TEXT, provider TEXT, model TEXT, mode TEXT, repetition INTEGER, warmup INTEGER DEFAULT 0,"
              " order_index INTEGER, threshold REAL, jev_mode TEXT, jev_model TEXT, cache_enabled INTEGER, config_json TEXT,"
              " metrics_json TEXT, sources_json TEXT, context TEXT, answer TEXT, error TEXT);"
              "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at REAL, kind TEXT, config_json TEXT, notes TEXT);"
              "INSERT INTO runs (run_id, created_at, pipeline) VALUES ('old1', 1.0, 'baseline');")


def test_db_migration_idempotent_on_old_schema(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.executescript(OLD_SCHEMA)
    c.commit()
    c.close()
    for _ in range(3):                                   # re-opening must not fail or duplicate columns
        db = Database(p)
        cols = {r["name"] for r in db.query("PRAGMA table_info(runs)")}
        assert {"initial_model", "final_model", "escalation_count", "retry_count", "routing_strategy"} <= cols
        db.conn.close()
    db = Database(p)
    assert db.query("SELECT run_id FROM runs")[0]["run_id"] == "old1"
    assert db.query("SELECT routing_strategy FROM runs")[0]["routing_strategy"] is None
    for t in ("routing_decisions", "verification_results"):
        assert db.query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] == 0
    db.insert_routing_decision("old1", {"policy_version": "p", "registry_version": "r", "complexity": 0.3, "risk": "low",
                                        "tier": 1, "model": "m1", "effort": None, "verify": "LIGHT",
                                        "reason_codes": ["a", "b"], "router_tokens": 0, "router_cost": 0.0, "latency_ms": 0.2})
    db.insert_verification_result("old1", 1, "LIGHT", False, 0, 0.0, "fact_missing")
    d = db.routing_decision("old1")
    assert d["reason_codes"] == ["a", "b"] and d["tier"] == 1 and d["router_cost"] == 0.0
    assert db.verification_results("old1")[0]["passed"] is False
    db.conn.close()


def test_persist_roundtrip_and_endpoint(tmp_path, tasks):
    db = Database(tmp_path / "rb.db")
    app = FastAPI()
    app.include_router(costs_routing.router)
    app.dependency_overrides[costs_api.get_db] = lambda: db
    tc = TestClient(app, client=("127.0.0.1", 50000))
    r = tc.get("/api/costs/routing/summary").json()                    # empty DB
    assert r["has_data"] is False and r["verdict"]["value"] == "sem dados"
    sim = rb.run_benchmark(tasks[:8], priced_models(), rb.StubRunner())
    rb.persist(db, sim)
    r = tc.get("/api/costs/routing/summary").json()                    # only simulated runs -> still no data
    assert r["has_data"] is False and r["verdict"]["value"] == "sem dados" and r["simulated_records"] > 0
    # non-simulated records -> figures with origin labels
    real = rb.BenchResult([dict(x, simulated=False) for x in sim.records], {}, {})
    rb.persist(db, real, "real")
    r = tc.get("/api/costs/routing/summary").json()
    assert r["has_data"] is True and r["verdict"]["value"] in ("SIM", "NÃO", "sem dados")
    assert r["strategies"]["DYNAMIC_ROUTER"]["cost_per_solved_task"]["origin"] in ("measured", "estimated", "unavailable")
    assert db.query("SELECT COUNT(*) n FROM routing_decisions")[0]["n"] > 0
    db.conn.close()
