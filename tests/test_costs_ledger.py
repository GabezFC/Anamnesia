"""Costs ledger: migration, labelled origins, price_status, budget logic, pure aggregation."""
from __future__ import annotations

import sqlite3
import time

from app.database.db import Database
from app.services import costs as svc
from config.pricing import price_for, price_status

OLD_RUNS = """CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, session_id TEXT, created_at REAL, question_id TEXT, query TEXT,
  pipeline TEXT, agent TEXT, provider TEXT, model TEXT, mode TEXT, repetition INTEGER,
  warmup INTEGER DEFAULT 0, order_index INTEGER, threshold REAL, jev_mode TEXT, jev_model TEXT,
  cache_enabled INTEGER, config_json TEXT, metrics_json TEXT, sources_json TEXT,
  context TEXT, answer TEXT, error TEXT)"""


def mk_run(run_id, pipeline="baseline", scope="projeto:anamnesia", created_at=None, **metrics):
    m = {"scope": scope, "pipeline": pipeline, "context_tokens": 100, "candidate_tokens_before_filter": 400,
         "total_tokens_spent": 100, "total_latency_ms": 12.0}
    m.update(metrics)
    return {"run_id": run_id, "session_id": "s", "created_at": created_at or time.time(), "query": "pergunta",
            "pipeline": pipeline, "agent": "mcp", "mode": "retrieval", "metrics_json": m,
            "jev_model": "jev-1.13.0" if "jev" in pipeline else None, "context": "ctx", "answer": None}


def jev_run(run_id, **kw):
    return mk_run(run_id, "graphify_jev", jev_input_tokens=1000, jev_output_tokens=10, judge_tokens=1010,
                  total_tokens_spent=1110, jev_cost=0.000042, **kw)


def test_migration_old_schema_and_idempotent(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute(OLD_RUNS)
    con.execute("INSERT INTO runs (run_id, created_at, pipeline) VALUES ('old1', 1.0, 'baseline')")
    con.commit(); con.close()
    for _ in range(2):  # second open must be a no-op
        db = Database(p)
        cols = {r["name"] for r in db.query("PRAGMA table_info(runs)")}
        assert {"project", "terminal_session_id", "cost_origin"} <= cols
        idx = {r["name"] for r in db.query("PRAGMA index_list(runs)")}
        assert {"runs_project_created", "runs_created_at"} <= idx
        assert db.get_run("old1")["project"] is None  # old row survives, nothing invented
        assert db.query("SELECT COUNT(*) AS n FROM budgets")[0]["n"] == 0
        db.conn.close()


def test_save_run_populates_project_terminal_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("MG_TERMINAL_SESSION", "term-7")
    db = Database(tmp_path / "a.db")
    db.save_run(mk_run("r1", scope="projeto:anamnesia"))
    db.save_run(mk_run("r2", scope="global"))
    db.save_run(jev_run("r3", scope="projeto:a,area:x"))
    r1, r2, r3 = (db.get_run(i) for i in ("r1", "r2", "r3"))
    assert r1["project"] == "anamnesia" and r1["terminal_session_id"] == "term-7"
    assert r1["cost_origin"] == "estimated"
    assert r2["project"] is None
    assert r3["project"] == "a" and r3["cost_origin"] == "measured"
    monkeypatch.delenv("MG_TERMINAL_SESSION")
    db.save_run(mk_run("r4"))
    assert db.get_run("r4")["terminal_session_id"] is None


def test_price_status_and_price_for_unchanged():
    assert price_status("jev-1.13.0")["status"] == "verified"
    assert price_status("jev-1.13.0")["checked"] == "2026-09-24"
    assert price_status("gpt-unknown")["status"] == "unavailable"
    assert price_status("whatever", "ollama")["status"] == "local_zero"
    assert price_for("gpt-unknown") is None and price_for("jev-1.13.0")["input"] == 0.042


def test_project_from_scope_and_origin():
    assert svc.project_from_scope("projeto:a,projeto:b") == "a,b"
    assert svc.project_from_scope("area:x") is None and svc.project_from_scope(None) is None
    assert svc.cost_origin_for({}, "baseline") == "unavailable"
    assert svc.cost_origin_for({"context_tokens": 5}, "baseline") == "estimated"
    assert svc.cost_origin_for({"jev_input_tokens": 5, "context_tokens": 5}, "graphify_jev") == "measured"


def test_summary_origins_and_null_money(tmp_path):
    rows = [dict(mk_run("a"), metrics_json=mk_run("a")["metrics_json"])]
    # JEV model without a verified price => money must be null, never guessed
    unpriced = jev_run("u")
    unpriced["jev_model"] = "jev-unknown-model"
    s = svc.summarize([unpriced])
    assert s["cost_usd"] == {"value": None, "origin": "unavailable"} and s["priced_calls"] == 0
    assert s["context_tokens"]["origin"] == "estimated"
    assert s["judge_tokens"] == {"value": 1010, "origin": "measured"}
    s2 = svc.summarize([jev_run("j"), jev_run("k")] + rows)
    assert s2["cost_usd"]["value"] == 0.000084 and s2["cost_usd"]["origin"] == "measured"
    assert s2["judge_tokens"]["value"] == 2020 and s2["calls"] == 3
    assert svc.summarize([])["cost_usd"]["value"] is None


def test_judge_tokens_unavailable_when_jev_usage_missing():
    r = mk_run("x", "graphify_jev")  # JEV pipeline without reported usage
    f = svc.run_figures(r)
    assert f["judge_tokens"] == {"value": None, "origin": "unavailable"}
    assert f["cost_usd"]["value"] is None


def test_budget_status_thresholds():
    assert svc.budget_status(0.5, 1.0)["status"] == "ok"
    assert svc.budget_status(0.8, 1.0)["status"] == "warn"
    assert svc.budget_status(1.0, 1.0)["status"] == "exceeded"
    assert svc.budget_status(None, 1.0)["status"] == "ok"
    assert svc.budget_status(5.0, None)["status"] == "ok"


def test_budget_storage_roundtrip(tmp_path):
    db = Database(tmp_path / "b.db")
    db.set_budget("day", 1.5); db.set_budget("month", 20)
    assert db.get_budgets() == {"day": 1.5, "month": 20.0}
    db.set_budget("day", None)
    assert db.get_budgets() == {"month": 20.0}


def test_cost_rows_keyset_and_project_filter(tmp_path):
    db = Database(tmp_path / "c.db")
    for i in range(5):
        db.save_run(mk_run(f"r{i}", created_at=1000.0 + i, scope="projeto:p" if i % 2 else "global"))
    page1 = db.cost_rows(limit=2)
    assert [r["run_id"] for r in page1] == ["r4", "r3"]
    page2 = db.cost_rows(limit=2, before=(page1[-1]["created_at"], page1[-1]["run_id"]))
    assert [r["run_id"] for r in page2] == ["r2", "r1"]
    assert {r["run_id"] for r in db.cost_rows(project="p")} == {"r1", "r3"}
    assert db.cost_rows(since=1003.0)[-1]["run_id"] == "r3"
