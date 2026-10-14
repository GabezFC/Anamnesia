"""T6.4 / G5: personal ceiling at 100% degrades the requested paid pipeline to baseline (offline)."""
from __future__ import annotations

import pytest

from app.database.db import Database
from app.gateway import budget_guard as bg
from app.gateway.budget_guard import BudgetGuard
from app.gateway.optimizer import Plan
from tests.test_budget_and_measurement import CountingBackend, make_gw
from tests.test_costs_ledger import jev_run, mk_run

SPEND = 0.000042   # measured cost of one jev_run


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for f in (bg.ENV_FLAG, bg.DEGRADE_FLAG, bg.WARN_FLAG):
        monkeypatch.delenv(f, raising=False)


def plan(p="graphify_jev"):
    return Plan("graphify_jev", p, None, "explicit")


def mkdb(tmp_path, day=None, month=None, runs=1):
    db = Database(tmp_path / "g.db")
    for i in range(runs):
        db.save_run(jev_run(f"j{i}"))
    if day is not None:
        db.set_budget("day", day)
    if month is not None:
        db.set_budget("month", month)
    return db


def test_flag_default_follows_ceiling():
    assert bg.enforcement_enabled(None) is False
    assert bg.enforcement_enabled({"day": None, "month": None}) is False
    assert bg.enforcement_enabled({"day": 0, "month": 0}) is False
    assert bg.enforcement_enabled({"day": 0, "month": 5.0}) is True


def test_explicit_flag_wins(monkeypatch):
    monkeypatch.setenv(bg.DEGRADE_FLAG, "0")
    assert bg.enforcement_enabled({"day": 1.0}) is False
    monkeypatch.setenv(bg.DEGRADE_FLAG, "1")
    assert bg.enforcement_enabled({}) is True


def test_100pct_degrades_without_any_flag(tmp_path):
    db = mkdb(tmp_path, day=SPEND)            # exactly 100%
    new, extra = BudgetGuard(ttl_s=0).apply(plan(), db)
    assert new.pipeline == "baseline" and new.requested == "graphify_jev"
    assert extra["budget_degraded"] is True
    assert extra["budget_requested_pipeline"] == "graphify_jev"
    assert extra["budget_effective_pipeline"] == "baseline"
    assert "graphify_jev -> baseline" in extra["budget_degraded_reason"]
    assert extra["budget_warning"]


def test_80pct_only_warns(tmp_path):
    db = mkdb(tmp_path, day=SPEND / 0.85)
    pl = plan()
    new, extra = BudgetGuard(ttl_s=0).apply(pl, db)
    assert new is pl and extra["budget_status"] == "warn" and extra["budget_warning"]
    assert "budget_degraded" not in extra


def test_below_80_is_silent_ok(tmp_path):
    pl = plan()
    new, extra = BudgetGuard(ttl_s=0).apply(pl, mkdb(tmp_path, day=SPEND * 10))
    assert new is pl and extra["budget_status"] == "ok" and "budget_warning" not in extra


def test_no_ceiling_or_zero_never_degrades(tmp_path):
    for i, kw in enumerate(({}, {"day": 0, "month": 0})):
        d = tmp_path / str(i)
        d.mkdir()
        pl = plan()
        new, extra = BudgetGuard(ttl_s=0).apply(pl, mkdb(d, **kw))
        assert new is pl and "budget_degraded" not in extra


def test_degrade_off_flag_keeps_pipeline_and_warns(tmp_path, monkeypatch):
    monkeypatch.setenv(bg.DEGRADE_FLAG, "0")
    pl = plan()
    new, extra = BudgetGuard(ttl_s=0).apply(pl, mkdb(tmp_path, day=SPEND / 2))
    assert new is pl and extra["budget_mode"] == "warn" and extra["budget_warning"]


def test_unknown_spend_does_not_degrade_but_warns(tmp_path):
    db = Database(tmp_path / "u.db")
    db.save_run(mk_run("u1", "graphify_jev"))   # JEV run with no measured cost -> unknown spend
    db.set_budget("day", 0.0001)
    pl = plan()
    new, extra = BudgetGuard(ttl_s=0).apply(pl, db)
    assert new is pl and "budget_degraded" not in extra
    assert extra["budget_status"] == "unknown" and "desconhecido" in extra["budget_warning"]


def test_free_pipelines_untouched(tmp_path):
    db = mkdb(tmp_path, day=SPEND / 2)
    for p in ("baseline", "graphify"):
        pl = plan(p)
        assert BudgetGuard(ttl_s=0).apply(pl, db) == (pl, {})


def test_gateway_end_to_end_degrades_offline(tiny_vault, tmp_path):
    be = CountingBackend()
    gw = make_gw(tiny_vault, tmp_path, be)      # spend 0.000042 vs day ceiling 0.00001
    r = gw.search("Qual o banco escolhido?", "graphify_jev", 5, persist=False)
    assert r.pipeline == "baseline" and be.calls == 0      # no JEV / paid call
    m = r.metrics
    assert m["budget_degraded"] is True and m["budget_requested_pipeline"] == "graphify_jev"
    assert m["budget_effective_pipeline"] == "baseline" and m["budget_warning"]


def test_budget_route_reports_degrade(tmp_path):
    from app.api.costs_ext import budget_view
    v = budget_view(mkdb(tmp_path, day=SPEND / 2))
    assert v["degrade"] == {"enabled": True, "fallback_pipeline": "baseline", "active": True, "unknown_spend": []}
    d = tmp_path / "n"
    d.mkdir()
    assert budget_view(mkdb(d))["degrade"]["enabled"] is False
