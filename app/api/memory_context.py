"""Memory screen helpers: the context of the last search and a free preview.

GET /api/memory/last-search  -> the newest recorded search (REST/MCP/CLI; persisted in `runs`, so it
                                survives restarts): real sources, tokens, and the context text.
GET /api/memory/search-preview?q= -> sources + token estimate for a query WITHOUT recording a run and
                                without any paid stage (baseline pipeline, zero model tokens).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.costs import get_db
from app.database.db import Database

router = APIRouter(prefix="/api/memory")
PREVIEW_PIPELINES = ("baseline", "graphify")  # free: no judge/model call (JEV pipelines are paid -> excluded)


def _metrics_only() -> bool:
    return os.environ.get("MG_METRICS_ONLY", "").strip().lower() in ("1", "true", "yes", "on")


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def view_of_run(run: dict, metrics_only: bool) -> dict:
    m = run.get("metrics") or {}
    srcs = run.get("sources") or []
    return {
        "run_id": run.get("run_id"), "created_at": run.get("created_at"),
        "query": None if metrics_only else run.get("query"),
        "pipeline": run.get("pipeline"), "agent": run.get("agent"), "client": m.get("client"),
        "sources": [{"file": s.get("file"), "section": s.get("section"), "score": s.get("score"),
                     "relevance": s.get("relevance"), "decision": s.get("decision"),
                     "tokens": s.get("tokens", 0), "why": s.get("why", "")} for s in srcs],
        "tokens": {"context": _num(m.get("context_tokens")), "candidates": _num(m.get("candidate_tokens_before_filter")),
                   "total_spent": _num(m.get("total_tokens_spent")),
                   "sources_sum": sum(int(s.get("tokens") or 0) for s in srcs)},
        "latency_ms": _num(m.get("total_latency_ms")),
        "cache_hit": m.get("result_cache_hit"),
        "context": None if metrics_only else run.get("context"),
        "metrics_only": metrics_only,
    }


@router.get("/last-search")
def last_search(db: Database = Depends(get_db)) -> dict:
    """404-free: `{"found": false}` when nothing was searched yet."""
    run = db.last_search_run()
    if not run:
        return {"found": False}
    return {"found": True, **view_of_run(run, _metrics_only())}


@router.get("/search-preview")
def search_preview(q: str = Query(..., min_length=1, max_length=2000), max_results: int = Query(10, ge=1, le=50),
                   scope: str | None = Query(None, max_length=500),
                   pipeline: str = Query("baseline", max_length=40)) -> dict:
    """Free preview, never recorded. ANA-208: `pipeline` may be baseline|graphify (both local, zero model
    tokens). The JEV pipelines call a paid judge, so a preview of them is refused (422), not silently run."""
    from app.api import routes
    if pipeline not in PREVIEW_PIPELINES:
        raise HTTPException(422, f"pipeline de prévia inválido: {pipeline}. Gratuitos: {list(PREVIEW_PIPELINES)}")
    try:
        r = routes.gw().search(q, pipeline, max_results, scope=scope, persist=False)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    m = r.metrics or {}
    srcs = [s.to_dict() for s in r.sources]
    return {"query": q, "pipeline": r.pipeline, "recorded": False, "sources": srcs,
            "tokens": {"context": _num(m.get("context_tokens")), "candidates": _num(m.get("candidate_tokens_before_filter")),
                       "sources_sum": sum(int(s.get("tokens") or 0) for s in srcs)}}
