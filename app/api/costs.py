"""Per-call cost ledger API (/api/costs/*). Read-only except PUT /budget (local write guard)."""
from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.database.db import Database
from app.services import costs as svc
from app.services.security import require_local_write

router = APIRouter(prefix="/api/costs")


def get_db() -> Database:
    """Default: the running gateway's database. Tests override this dependency."""
    from app.api import routes
    return routes.gw().db


def metrics_only() -> bool:
    return os.environ.get("MG_METRICS_ONLY", "").strip().lower() in ("1", "true", "yes", "on")


@router.get("/summary")
def summary(range: str = Query("today", pattern="^(today|7d|30d|all)$"), project: str | None = None,
            db: Database = Depends(get_db)) -> dict:
    now = time.time()
    rows = db.cost_rows(since=svc.range_since(range, now), project=project)
    day_rows = db.cost_rows(since=svc.range_since("today", now), project=project)
    month_rows = db.cost_rows(since=svc.range_since("30d", now), project=project)
    return svc.summarize(rows, range, db.get_budgets(), svc.spend_of(day_rows), svc.spend_of(month_rows))


def _encode_cursor(row: dict) -> str:
    return f"{row['created_at']!r}|{row['run_id']}"


def _decode_cursor(c: str) -> tuple[float, str]:
    try:
        ts, rid = c.split("|", 1)
        return float(ts), rid
    except ValueError:
        raise HTTPException(400, "cursor inválido")


@router.get("/calls")
def calls(cursor: str | None = None, limit: int = Query(50, ge=1, le=500), project: str | None = None,
          db: Database = Depends(get_db)) -> dict:
    before = _decode_cursor(cursor) if cursor else None
    rows = db.cost_rows(project=project, limit=limit + 1, before=before)
    page = rows[:limit]
    mo = metrics_only()
    return {"items": [svc.call_view(r, mo) for r in page],
            "next_cursor": _encode_cursor(page[-1]) if len(rows) > limit else None,
            "metrics_only": mo}


@router.get("/calls/{run_id}")
def call_detail(run_id: str, db: Database = Depends(get_db)) -> dict:
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(404, "chamada não encontrada")
    row = dict(run)
    row["metrics_json"] = run.get("metrics") or {}
    mo = metrics_only()
    out = svc.call_view(row, mo)
    out["sources"] = run.get("sources") or []
    out["candidates"] = run.get("candidates") or []
    out["metrics"] = run.get("metrics") or {}
    if not mo:
        out["context"] = run.get("context")
        out["answer"] = run.get("answer")
    out["metrics_only"] = mo
    return out


@router.get("/export.csv")
def export_csv(range: str = Query("all", pattern="^(today|7d|30d|all)$"), project: str | None = None,
               db: Database = Depends(get_db)) -> Response:
    mo = metrics_only()
    fields = list(svc.CSV_FIELDS) + ([] if mo else ["query"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in db.cost_rows(since=svc.range_since(range), project=project):
        w.writerow(svc.csv_row(svc.call_view(r, mo), mo))
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="custos.csv"'})


class BudgetIn(BaseModel):
    period: str
    ceiling_usd: float | None = None


@router.put("/budget", dependencies=[Depends(require_local_write)])
def put_budget(body: BudgetIn, db: Database = Depends(get_db)) -> dict:
    if body.period not in svc.BUDGET_PERIODS:
        raise HTTPException(422, f"period deve ser um de {svc.BUDGET_PERIODS}")
    if body.ceiling_usd is not None and body.ceiling_usd < 0:
        raise HTTPException(422, "ceiling_usd deve ser >= 0")
    db.set_budget(body.period, body.ceiling_usd)
    return {"budgets": db.get_budgets()}


@router.get("/stream")
def stream(max_seconds: float = Query(300.0, ge=0, le=3600), max_events: int = Query(0, ge=0),
           poll_interval: float = Query(1.0, ge=0.01, le=10), after_rowid: int | None = Query(None, ge=0),
           db: Database = Depends(get_db)) -> StreamingResponse:
    """SSE: one `call` event per new run. Ends after max_seconds (or max_events if >0)."""
    mo = metrics_only()

    def gen() -> Iterator[str]:
        last = db.max_run_rowid() if after_rowid is None else after_rowid
        deadline = time.monotonic() + max_seconds
        sent = 0
        yield ": connected\n\n"
        while True:
            for r in db.cost_rows_after_rowid(last):
                last = max(last, r["_rowid"])
                data = json.dumps(svc.call_view(r, mo), ensure_ascii=False, default=str)
                yield f"event: call\nid: {r['_rowid']}\ndata: {data}\n\n"
                sent += 1
                if max_events and sent >= max_events:
                    yield "event: end\ndata: {}\n\n"
                    return
            if time.monotonic() >= deadline:
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
