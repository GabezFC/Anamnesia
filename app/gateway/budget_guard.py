"""Budget guard (T6.4): optionally degrade paid pipelines to the free baseline once the ceiling is hit.

OFF by default. With `ANAMNESIA_BUDGET_ENFORCE` unset/0, `apply()` returns immediately: no DB read,
no metric, no change of plan -- the search path is byte-identical to before this module existed.

With `ANAMNESIA_BUDGET_ENFORCE=1`, and only for a plan whose pipeline spends paid tokens (the JEV
pipelines: graphify_jev, graphify_jev_opt):
  * status `exceeded` (spend >= ceiling, day or month)  -> plan is rewritten to `baseline`;
    metrics get budget_degraded=True, budget_degraded_reason, budget_requested_pipeline.
  * status `warn` (>= 80%)                              -> only `budget_warning` is added.
  * status `ok`                                          -> `budget_status: "ok"` only.
Free pipelines are never touched and never cause a DB read.

Spend and ceilings come from the same read-only helpers as the cost ledger (`Database.get_budgets`,
`Database.cost_rows`, `app.services.costs.spend_of/budget_status`); day = since 00:00 local,
month = last 30 days, exactly like GET /api/costs/summary. A failure to read them never blocks a
search (status `unknown`, no degradation). Unknown spend or no ceiling is never an alarm.
"""
from __future__ import annotations

import os
import time
from dataclasses import replace
from typing import Any

from app.schemas.models import JEV_PIPELINES
from app.services import costs as svc

ENV_FLAG = "ANAMNESIA_BUDGET_ENFORCE"
FALLBACK_PIPELINE = "baseline"
_ORDER = {"ok": 0, "warn": 1, "exceeded": 2}
_CACHE_TTL_S = 5.0   # spend is re-read at most every few seconds per guard (a search is ~ms)


def enforcement_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def spends_paid_tokens(pipeline: str | None) -> bool:
    return pipeline in JEV_PIPELINES


def evaluate(db, now: float | None = None) -> dict:
    """Budgets + current spend -> {"status": ok|warn|exceeded, "worst_period", "day", "month"}."""
    now = time.time() if now is None else now
    budgets = db.get_budgets()
    day_rows = db.cost_rows(since=svc.range_since("today", now))
    month_rows = db.cost_rows(since=svc.range_since("30d", now))
    per = {"day": svc.budget_status(svc.spend_of(day_rows), budgets.get("day")),
           "month": svc.budget_status(svc.spend_of(month_rows), budgets.get("month"))}
    worst = max(per, key=lambda p: _ORDER[per[p]["status"]])
    return {"status": per[worst]["status"], "worst_period": worst if per[worst]["status"] != "ok" else None,
            "day": per["day"], "month": per["month"]}


class BudgetGuard:
    def __init__(self, ttl_s: float = _CACHE_TTL_S):
        self.ttl = ttl_s
        self._cached: tuple[float, dict] | None = None

    def state(self, db, now: float | None = None) -> dict:
        t = time.monotonic()
        if self._cached and t - self._cached[0] < self.ttl:
            return self._cached[1]
        st = evaluate(db, now)
        self._cached = (t, st)
        return st

    def apply(self, plan, db) -> tuple[Any, dict]:
        """Returns (plan, extra_metrics). Identity + {} unless enforcement is on and the plan is paid."""
        if not enforcement_enabled() or not spends_paid_tokens(plan.pipeline):
            return plan, {}
        try:
            st = self.state(db)
        except Exception as exc:  # noqa: BLE001 -- the guard must never block a search
            return plan, {"budget_status": "unknown", "budget_guard_error": type(exc).__name__}
        extra: dict[str, Any] = {"budget_status": st["status"]}
        if st["status"] == "warn":
            p = st["worst_period"]
            extra["budget_warning"] = (f"gasto {st[p]['ratio']:.0%} do teto {p} "
                                       f"(US$ {st[p]['spent_usd']} de {st[p]['ceiling_usd']})")
        elif st["status"] == "exceeded":
            p = st["worst_period"]
            reason = (f"teto {p} excedido (US$ {st[p]['spent_usd']} >= {st[p]['ceiling_usd']}); "
                      f"{plan.pipeline} -> {FALLBACK_PIPELINE}")
            extra.update({"budget_degraded": True, "budget_degraded_reason": reason,
                          "budget_requested_pipeline": plan.pipeline})
            plan = replace(plan, pipeline=FALLBACK_PIPELINE, reason=f"budget_degraded:{p}")
        return plan, extra
