"""Read-only routing report for the Custos tab: GET /api/costs/routing/summary.

Include in main.py:  from app.api import costs_routing; app.include_router(costs_routing.router)
Only non-simulated benchmark runs (runs.routing_strategy IS NOT NULL, record.simulated false) produce figures;
stub runs are only counted. No data -> every verdict is 'sem dados'. Never writes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.costs import get_db
from app.benchmark.routing_bench import records_from_db
from app.database.db import Database
from app.routing import metrics as M

router = APIRouter(prefix="/api/costs")


def _empty(reason: str, simulated: int = 0) -> dict:
    return {"has_data": False, "verdict": {"value": "sem dados", "reason": reason}, "simulated_records": simulated,
            "n_records": 0, "strategies": {}, "break_even": None, "difficulty_tier_matrix": None,
            "escalation_rate": M.lv(None), "by_difficulty": {}, "origin_note": "medido / estimado / indisponível"}


@router.get("/routing/summary")
def routing_summary(db: Database = Depends(get_db)) -> dict:
    try:
        records = records_from_db(db)
    except Exception:  # noqa: BLE001  (old schema / no table: nothing to show)
        records = []
    if not records:
        return _empty("nenhuma execução de roteamento registrada")
    s = M.build_summary(records)
    if not s["has_data"]:
        return _empty("somente execuções simuladas (stub): não é evidência", s["simulated_records"])
    dyn = (s["strategies"].get(M.DYNAMIC) or {})
    s["by_difficulty"] = dyn.get("by_difficulty", {})
    s["origin_note"] = "medido / estimado / indisponível"
    return s
