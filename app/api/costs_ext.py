"""Cost API extensions: budget (daily/monthly + alert), hourly series, per-role cost.
Included in the same router as app/api/costs.py (imported at the bottom of that module)."""
from __future__ import annotations

import time

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.costs import RANGE_RE, get_db, router
from app.database.db import Database
from app.services import costs as svc
from app.services import costs_series as series
from app.services import settings_store
from app.services.security import require_local_write


def get_orchestrator():
    """Default: the shared orchestrator (read-only use). Tests override this dependency."""
    from app.api.orchestration import get_orchestrator as _get
    return _get()


class BudgetIn(BaseModel):
    """Legacy pair (period + ceiling_usd) and/or daily_usd / monthly_usd / alert_pct (any subset)."""
    period: str | None = None
    ceiling_usd: float | None = None
    daily_usd: float | None = Field(None, ge=0)
    monthly_usd: float | None = Field(None, ge=0)
    alert_pct: float | None = Field(None, gt=0, le=100)


def budget_view(db: Database) -> dict:
    now = time.time()
    budgets = db.get_budgets()
    pct = settings_store.alert_pct(db)
    spent = {"day": svc.spend_of(db.cost_rows(since=svc.range_since("today", now))),
             "month": svc.spend_of(db.cost_rows(since=svc.range_since("30d", now)))}
    out: dict = {"alert_pct": pct}
    for key, period in (("daily", "day"), ("monthly", "month")):
        limit, sp = budgets.get(period), spent[period]
        percent = round(sp / limit * 100, 2) if limit and limit > 0 and sp is not None else None
        out[key] = {"limit_usd": limit, "spent_usd": sp, "percent": percent,
                    "alert": percent is not None and percent >= pct,
                    "exceeded": percent is not None and percent >= 100}
    out["alert"] = out["daily"]["alert"] or out["monthly"]["alert"]
    out["budgets"] = budgets  # legacy shape {day, month}
    return out


@router.get("/budget")
def get_budget(db: Database = Depends(get_db)) -> dict:
    """spent / limit / percent per period + `alert` (percent >= alert_pct, default 80).
    daily = since local midnight; monthly = rolling 30 days (same windows as /summary)."""
    return budget_view(db)


@router.put("/budget", dependencies=[Depends(require_local_write)])
def put_budget(body: BudgetIn, db: Database = Depends(get_db)) -> dict:
    sent = body.model_fields_set
    if body.period is not None:
        if body.period not in svc.BUDGET_PERIODS:
            raise HTTPException(422, f"period deve ser um de {svc.BUDGET_PERIODS}")
        if body.ceiling_usd is not None and body.ceiling_usd < 0:
            raise HTTPException(422, "ceiling_usd deve ser >= 0")
        db.set_budget(body.period, body.ceiling_usd)
    elif "ceiling_usd" in sent:
        raise HTTPException(422, "ceiling_usd exige period")
    if "daily_usd" in sent:
        db.set_budget("day", body.daily_usd)
    if "monthly_usd" in sent:
        db.set_budget("month", body.monthly_usd)
    if body.alert_pct is not None:
        settings_store.save_patch(db, settings_store.SettingsPatch(budget={"alert_pct": body.alert_pct}))
    if body.period is not None and not ({"daily_usd", "monthly_usd", "alert_pct"} & sent):
        return {"budgets": db.get_budgets()}  # legacy request -> legacy response (unchanged contract)
    return budget_view(db)


@router.get("/hourly")
def hourly(range: str = Query("today", pattern=RANGE_RE), project: str | None = None,
           db: Database = Depends(get_db)) -> dict:
    """Per-hour series (server local time) from the ledger; zero-filled up to the current hour."""
    now = time.time()
    since = svc.range_since(range, now)
    return {"range": range, "points": series.hourly_series(db.cost_rows(since=since, project=project), since, now)}


@router.get("/by-role")
def by_role(range: str = Query("all", pattern=RANGE_RE), db: Database = Depends(get_db),
            orch=Depends(get_orchestrator)) -> dict:
    """Cost per subagent role. source="orchestration": steps of orchestrator runs in the range
    (role = researcher|implementer|reviewer); else source="agent": ledger grouped by `agent`."""
    since = svc.range_since(range)
    try:
        runs = orch.list(None)
    except Exception:  # noqa: BLE001 - orchestrator is optional for the ledger
        runs = []
    items = series.roles_from_orchestration(runs, since)
    source = "orchestration"
    if not items:
        source, items = "agent", series.roles_from_agents(db.cost_rows(since=since))
    return {"range": range, "source": source, "items": items}
