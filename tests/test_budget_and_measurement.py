"""T6.4 budget guard + T2 measurement pieces (estimator hook, cache hit-rate script, calibration script)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.database.db import Database
from app.gateway import budget_guard as bg
from app.gateway.budget_guard import BudgetGuard
from app.gateway.optimizer import Plan
from app.gateway import token_budget as tb
from app.services import token_estimate as te
from config.benchmark import BenchmarkConfig
from config.retrieval import RetrievalConfig
from tests.test_costs_ledger import jev_run, mk_run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(bg.ENV_FLAG, raising=False)
    monkeypatch.delenv(te.ENV_CALIBRATION, raising=False)


def db_with_spend(tmp_path, ceiling_day=None, ceiling_month=None, runs=1):
    db = Database(tmp_path / "g.db")
    for i in range(runs):
        db.save_run(jev_run(f"j{i}"))          # measured cost 0.000042 USD each, created now
    if ceiling_day is not None:
        db.set_budget("day", ceiling_day)
    if ceiling_month is not None:
        db.set_budget("month", ceiling_month)
    return db


# -- evaluate(): states ------------------------------------------------------------------------
def test_status_ok_without_ceiling(tmp_path):
    assert bg.evaluate(db_with_spend(tmp_path))["status"] == "ok"


def test_status_ok_warn_exceeded(tmp_path):
    spend = 0.000042
    for name, ceiling, expected in (("a", spend * 10, "ok"), ("b", spend / 0.9, "warn"), ("c", spend / 2, "exceeded")):
        d = tmp_path / name
        d.mkdir()
        st = bg.evaluate(db_with_spend(d, ceiling_day=ceiling))
        assert st["status"] == expected, (name, st)
    assert st["worst_period"] == "day"


def test_worst_of_day_and_month(tmp_path):
    st = bg.evaluate(db_with_spend(tmp_path, ceiling_day=1.0, ceiling_month=0.00001))
    assert st["status"] == "exceeded" and st["worst_period"] == "month"


# -- BudgetGuard.apply ---------------------------------------------------------------------------
def plan(p):
    return Plan("graphify_jev", p, None, "explicit")


def test_enforcement_off_by_default_is_identity_and_never_reads_db():
    class Boom:
        def __getattr__(self, k):
            raise AssertionError("db must not be touched when enforcement is off")
    pl = plan("graphify_jev")
    assert BudgetGuard().apply(pl, Boom()) == (pl, {})


def test_exceeded_with_enforce_degrades_paid_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv(bg.ENV_FLAG, "1")
    db = db_with_spend(tmp_path, ceiling_day=0.00001)
    for p in ("graphify_jev", "graphify_jev_opt"):
        new, extra = BudgetGuard(ttl_s=0).apply(plan(p), db)
        assert new.pipeline == "baseline" and new.requested == "graphify_jev"
        assert extra["budget_degraded"] is True and extra["budget_requested_pipeline"] == p
        assert "day" in extra["budget_degraded_reason"] and extra["budget_status"] == "exceeded"


def test_free_pipelines_never_degraded_even_if_exceeded(tmp_path, monkeypatch):
    monkeypatch.setenv(bg.ENV_FLAG, "1")
    db = db_with_spend(tmp_path, ceiling_day=0.00001)
    for p in ("baseline", "graphify"):
        pl = plan(p)
        assert BudgetGuard(ttl_s=0).apply(pl, db) == (pl, {})


def test_warn_adds_field_only(tmp_path, monkeypatch):
    monkeypatch.setenv(bg.ENV_FLAG, "1")
    db = db_with_spend(tmp_path, ceiling_day=0.000042 / 0.9)
    pl = plan("graphify_jev")
    new, extra = BudgetGuard(ttl_s=0).apply(pl, db)
    assert new is pl and "budget_warning" in extra and "budget_degraded" not in extra


def test_guard_failure_never_blocks(monkeypatch):
    monkeypatch.setenv(bg.ENV_FLAG, "1")
    class Bad:
        def get_budgets(self):
            raise RuntimeError("x")
    pl = plan("graphify_jev")
    new, extra = BudgetGuard(ttl_s=0).apply(pl, Bad())
    assert new is pl and extra["budget_status"] == "unknown"


# -- end to end through MemoryGateway.search ---------------------------------------------------------
class CountingBackend:
    def __init__(self):
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        return {k: 0.9 for k in questions}, {"input_tokens": 100, "output_tokens": 5}, "jev-test"


def make_gw(tiny_vault, tmp_path, backend):
    from app.gateway.memory_gateway import MemoryGateway
    rc = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    bc = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark", benchmark_mode=False)
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, jev_backend=backend)
    gw.warm()
    class _G:  # graphify CLI is not available in tests: serve graph candidates from the lexical index
        def build(self):
            return {}

        def search(self, query, limit=20):
            return gw.baseline.search(query, limit), {}
    gw.graphify = _G()
    gw.db.save_run(jev_run("spent1"))
    gw.db.set_budget("day", 0.00001)
    return gw


def test_gateway_default_unchanged_when_exceeded(tiny_vault, tmp_path):
    be = CountingBackend()
    gw = make_gw(tiny_vault, tmp_path, be)
    r = gw.search("Qual o banco escolhido?", "graphify_jev", 5, persist=False)
    assert r.pipeline == "graphify_jev" and be.calls >= 1
    assert "budget_degraded" not in r.metrics and "budget_status" not in r.metrics


def test_gateway_degrades_when_enforced(tiny_vault, tmp_path, monkeypatch):
    monkeypatch.setenv(bg.ENV_FLAG, "1")
    be = CountingBackend()
    gw = make_gw(tiny_vault, tmp_path, be)
    r = gw.search("Qual o banco escolhido?", "graphify_jev", 5, persist=False)
    assert r.pipeline == "baseline" and be.calls == 0
    assert r.metrics["budget_degraded"] is True and r.metrics["budget_requested_pipeline"] == "graphify_jev"
    assert r.metrics["pipeline_requested"] == "graphify_jev" and r.metrics["budget_degraded_reason"]


# -- token estimator hook -----------------------------------------------------------------------------
TXT_PT = "A decisão de usar o banco SQLite foi tomada para a aplicação, não para o servidor."


def test_estimator_default_identical_to_legacy():
    for t in ("", "x", TXT_PT, "plain english text for the test " * 20):
        for lang in ("auto", "pt", "other"):
            assert te.estimate_tokens(t, lang) == tb.estimate_tokens(t)


def test_estimator_uses_calibration_file_only_when_given(tmp_path, monkeypatch):
    f = tmp_path / "cal.json"
    f.write_text(json.dumps({"pt": 2.0, "other": 1.0}), encoding="utf-8")
    base = tb.estimate_tokens(TXT_PT)
    assert te.estimate_tokens(TXT_PT) == base                      # env unset -> unchanged
    monkeypatch.setenv(te.ENV_CALIBRATION, str(f))
    assert te.detect_lang(TXT_PT) == "pt"
    assert te.estimate_tokens(TXT_PT) > base                       # pt factor 2.0 applied (raw x 2.0)
    assert te.estimate_tokens(TXT_PT, "other") <= base             # factor 1.0 < 1.13
    monkeypatch.setenv(te.ENV_CALIBRATION, str(tmp_path / "missing.json"))
    assert te.estimate_tokens(TXT_PT) == base                      # invalid file -> default


# -- scripts ---------------------------------------------------------------------------------------------
def test_calibration_script_reads_copy_readonly(tmp_path):
    p = tmp_path / "c.db"
    db = Database(p)
    for i, real in enumerate((1200, 1300, 1250)):
        r = mk_run(f"r{i}", model_input_tokens=real, prompt_tokens_estimate=1000, consumer_model="qwen3:8b")
        r["agent"] = "generic"
        db.save_run(r)
    r = mk_run("agentrun", model_input_tokens=26000, prompt_tokens_estimate=1000, agent_tokens=27000)
    r["agent"] = "hermes"
    db.save_run(r)
    db.conn.close()
    sys.path.insert(0, str(ROOT / "scripts"))
    import calibrate_token_estimate as cal
    groups = cal.collect(str(p))
    assert list(groups.values())[0] == [1.2, 1.3, 1.25] and len(groups) == 1
    assert cal.summarize(groups[next(iter(groups))])["n"] == 3
    with pytest.raises(sqlite3.OperationalError):  # read-only open: writes impossible
        con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
        con.execute("DELETE FROM runs")


def test_cache_hit_rate_script_runs_on_stub(tmp_path):
    out = tmp_path / "o.json"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "measure_cache_hit_rate.py"),
                        "--queries", "4", "--json", str(out)],
                       capture_output=True, text=True, cwd=ROOT, timeout=240)
    assert r.returncode == 0, r.stderr[-800:]
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["cold"]["jev_candidate_cache"]["hits"] == 0
    assert d["warm"]["jev_candidate_cache"]["hits"] > 0 and d["warm"]["jev_candidate_cache"]["hit_rate"] == 1.0
    assert d["warm"]["jev_backend_calls"] == 0 and d["cold"]["jev_backend_calls"] > 0
    fw = d["free_pipeline_result_cache"]
    assert fw["warm"]["result_cache"]["hits"] > 0 and fw["cold"]["result_cache"]["hits"] == 0
    assert "mecanismo" in d["disclaimer"]
