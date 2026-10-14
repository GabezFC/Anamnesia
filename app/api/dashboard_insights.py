"""Read-only endpoints for the dashboard (Onda 7): regression alerts, provider health, memory lineage.

All GET, no writes, no paid calls, no prompts/secrets in the payloads (only counts, ids and paths already
shown elsewhere). They reuse the existing `get_db` dependency so tests can swap the database.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from app.api.costs import get_db
from app.database.db import Database
from app.services import dashboard_insights as ins

router = APIRouter(prefix="/api")


@router.get("/alerts")
def alerts(window: int = Query(20, ge=5, le=500), tokens_pct: float | None = Query(None, ge=0, le=1000),
           latency_p95_pct: float | None = Query(None, ge=0, le=1000), cost_pct: float | None = Query(None, ge=0, le=1000),
           db: Database = Depends(get_db)) -> dict:
    """Regression alerts: newest `window` runs vs the `window` before, per pipeline (ANA-202)."""
    from app.services import settings_store
    th = dict(settings_store.load_settings(db).regression_thresholds)   # persisted in /api/settings
    th.update({k: v for k, v in (("tokens_pct", tokens_pct), ("latency_p95_pct", latency_p95_pct), ("cost_pct", cost_pct))
               if v is not None})                                         # the query string wins
    runs = db.list_runs(limit=window * 2 * 4)  # 4 pipelines
    return ins.regression_alerts(runs, window=window, thresholds=th)


@router.get("/providers/health")
def providers_health(last_n: int = Query(100, ge=1, le=1000), db: Database = Depends(get_db)) -> dict:
    """Error rate / latency per provider over the last N recorded calls (ANA-210). Never probes."""
    runs = db.list_runs(limit=last_n)
    integrations: list[dict] = []
    try:
        from app.adapters.registry import detect_all
        integrations = list((detect_all(False) or {}).get("agents") or [])
    except Exception:  # noqa: BLE001 -- availability is optional; the ledger part still answers
        integrations = []
    return ins.provider_health(runs, integrations, last_n=last_n)


@router.get("/memory/lineage")
def memory_lineage(limit_runs: int = Query(500, ge=1, le=5000), db: Database = Depends(get_db)) -> dict:
    """Saved note -> origin (agent/project/source) and the runs that cited it (ANA-213)."""
    from app.api.memory_store import get_store
    notes = [n.to_dict(with_content=False) for n in get_store().list(include_expired=True)]
    rows = db.query("SELECT run_id, created_at, pipeline, agent, sources_json FROM runs "
                    "WHERE sources_json IS NOT NULL ORDER BY created_at DESC LIMIT ?", (limit_runs,))
    runs = []
    for r in rows:
        try:
            srcs = json.loads(r["sources_json"]) if r.get("sources_json") else []
        except ValueError:
            srcs = []
        runs.append({"run_id": r["run_id"], "created_at": r["created_at"], "pipeline": r["pipeline"],
                     "agent": r["agent"], "sources": srcs if isinstance(srcs, list) else []})
    return ins.memory_lineage(notes, runs)
