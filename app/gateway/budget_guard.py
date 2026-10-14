"""Budget guard (T6.4): optionally degrade paid pipelines to the free baseline once the ceiling is hit.

ENFORCEMENT is OFF by default. ANA-180: WARN mode is ON by default -- for paid plans the budget state is only
recorded in the metrics (never blocks, never changes the plan); `ANAMNESIA_BUDGET_WARN=0` restores the old inert path.
Free plans never read the DB.

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
DEGRADE_FLAG = "ANAMNESIA_BUDGET_DEGRADE"   # T6.4: explicit 0/1 wins; unset -> ON only when a ceiling is configured
WARN_FLAG = "ANAMNESIA_BUDGET_WARN"   # ANA-180: warn mode is ON by default; =0/off silences it (rollback)
FALLBACK_PIPELINE = "baseline"
_ORDER = {"ok": 0, "warn": 1, "exceeded": 2}
_CACHE_TTL_S = 5.0   # spend is re-read at most every few seconds per guard (a search is ~ms)


def has_ceiling(budgets: dict | None) -> bool:
    return any((v or 0) > 0 for v in (budgets or {}).values() if isinstance(v, (int, float)))


def enforcement_enabled(budgets: dict | None = None) -> bool:
    """T6.4: ANAMNESIA_BUDGET_DEGRADE (explicit 0/1) wins, then the legacy ANAMNESIA_BUDGET_ENFORCE.
    Unset -> ON only when a day/month ceiling (>0) is configured (`budgets`); empty/0 = no ceiling = OFF."""
    for flag in (DEGRADE_FLAG, ENV_FLAG):
        raw = os.environ.get(flag, "").strip().lower()
        if raw:
            return raw in ("1", "true", "yes", "on")
    return has_ceiling(budgets)


def warn_enabled() -> bool:
    """ANA-180: default ON. Warn mode only *records* the budget state of paid searches; it never blocks."""
    return os.environ.get(WARN_FLAG, "").strip().lower() not in ("0", "false", "no", "off")


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
            "day": per["day"], "month": per["month"], "budgets": budgets,
            "unknown_spend": [p for p, b in per.items() if b["spent_usd"] is None and (b["ceiling_usd"] or 0) > 0]}


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
        """Returns (plan, extra_metrics).

        Paid plan + enforcement on  -> may degrade to baseline (as before).
        Paid plan + enforcement off -> ANA-180 warn mode (default): the budget state is recorded
        (`budget_status`, `budget_mode: "warn"`, `budget_warning`) and the plan is NEVER changed.
        Free plans, or warn mode switched off (ANAMNESIA_BUDGET_WARN=0) -> identity + {}.
        """
        if not spends_paid_tokens(plan.pipeline):
            return plan, {}
        try:
            enforce = enforcement_enabled(db.get_budgets())
        except Exception:  # noqa: BLE001
            enforce = enforcement_enabled()
        if not enforce and not warn_enabled():
            return plan, {}
        try:
            st = self.state(db)
        except Exception as exc:  # noqa: BLE001 -- the guard must never block a search
            return plan, {"budget_status": "unknown", "budget_guard_error": type(exc).__name__}
        extra: dict[str, Any] = {"budget_status": st["status"]}
        if not enforce:
            extra["budget_mode"] = "warn"
        if st.get("unknown_spend") and st["status"] == "ok":
            extra["budget_status"] = "unknown"   # ceiling set but spend unknown: never degrades, but warns
            extra["budget_warning"] = f"gasto desconhecido (teto {', '.join(st['unknown_spend'])}); sem degradação"
        if st["status"] == "warn" or (st["status"] == "exceeded" and not enforce):
            p = st["worst_period"]
            extra["budget_warning"] = (f"gasto {st[p]['ratio']:.0%} do teto {p} "
                                       f"(US$ {st[p]['spent_usd']} de {st[p]['ceiling_usd']})")
        if st["status"] == "exceeded" and enforce:
            p = st["worst_period"]
            reason = (f"teto {p} excedido (US$ {st[p]['spent_usd']} >= {st[p]['ceiling_usd']}); "
                      f"{plan.pipeline} -> {FALLBACK_PIPELINE}")
            extra.update({"budget_degraded": True, "budget_degraded_reason": reason,
                          "budget_requested_pipeline": plan.pipeline,
                          "budget_effective_pipeline": FALLBACK_PIPELINE,
                          "budget_warning": f"teto {p} atingido: pipeline degradado para {FALLBACK_PIPELINE}"})
            plan = replace(plan, pipeline=FALLBACK_PIPELINE, reason=f"budget_degraded:{p}")
        return plan, extra
