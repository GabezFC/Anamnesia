"""Server-side benchmark aggregation + exportable report (GET /api/benchmark/aggregate, /report.md|.json).

Replaces the front downloading hundreds of runs: one query over the `runs` table, grouped by pipeline.
Observed numbers only (no verdicts), warm-up runs excluded unless asked.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api.costs import RANGE_RE, get_db
from app.benchmark.statistics import describe
from app.database.db import Database
from app.services import costs as svc

router = APIRouter(prefix="/api/benchmark")

# output key -> metrics_json key
METRICS = {"latency_ms": "total_latency_ms", "context_tokens": "context_tokens",
           "candidate_tokens": "candidate_tokens_before_filter", "total_tokens": "total_tokens_spent",
           "judge_tokens": "judge_tokens", "context_reduction": "context_reduction"}
SCORES = ("accuracy", "completeness", "groundedness", "citation_quality")


def _stat(values) -> dict:
    d = describe(values)
    return {"n": d["n"], "mean": d["mean"], "p50": d["median"], "p95": d["p95"], "min": d["min"], "max": d["max"]}


def _metrics(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        m = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return m if isinstance(m, dict) else {}


def build_aggregate(db: Database, range_: str = "all", session_id: str | None = None,
                    include_warmup: bool = False, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    since = svc.range_since(range_, now)
    rows = db.benchmark_rows(session_id=session_id, since=since, include_warmup=include_warmup)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["pipeline"] or "?", []).append(r)
    scores = {s["pipeline"]: s for s in db.evaluation_scores(session_id=session_id, since=since)}
    out = []
    for pipe, rs in sorted(groups.items()):
        ms = [_metrics(r["metrics_json"]) for r in rs]
        costs = [svc.run_figures({"pipeline": pipe, "metrics_json": r["metrics_json"],
                                  "jev_model": r.get("jev_model")})["cost_usd"]["value"] for r in rs]
        # Prefer the stored total_cost (set by the runner); fall back to jev_cost via the ledger rule.
        costs = [m.get("total_cost") if m.get("total_cost") is not None else c for m, c in zip(ms, costs)]
        known = [c for c in costs if c is not None]
        sc = scores.get(pipe)
        row = {"pipeline": pipe, "n": len(rs), "errors": sum(1 for r in rs if r.get("error")),
               "cost_usd": {"total": round(sum(known), 8) if known else None,
                            "mean": round(sum(known) / len(known), 8) if known else None,
                            "n": len(known), **{k: v for k, v in _stat(known).items() if k in ("p50", "p95")}},
               "scores": {"n": sc["n"] if sc else 0,
                          **{k: (round(sc[k], 3) if sc and sc[k] is not None else None) for k in SCORES}}}
        for out_key, mk in METRICS.items():
            row[out_key] = _stat(m.get(mk) for m in ms)
        out.append(row)
    return {"range": range_, "session_id": session_id, "include_warmup": include_warmup,
            "generated_at": now, "total_runs": len(rows), "pipelines": out}


@router.get("/aggregate")
def aggregate(range: str = Query("all", pattern=RANGE_RE), session_id: str | None = None,
              include_warmup: bool = False, db: Database = Depends(get_db)) -> dict:
    return build_aggregate(db, range, session_id, include_warmup)


def _f(v, nd=1) -> str:
    if v is None:
        return "n/d"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def render_markdown(agg: dict) -> str:
    when = datetime.fromtimestamp(agg["generated_at"]).strftime("%Y-%m-%d %H:%M")
    lines = ["# Relatório do Laboratório — Anamnésia", "",
             f"Gerado em {when} · período: `{agg['range']}`"
             + (f" · sessão: `{agg['session_id']}`" if agg["session_id"] else "")
             + f" · {agg['total_runs']} execuções (warm-up {'incluído' if agg['include_warmup'] else 'excluído'}). "
             "Números observados; sem veredito.", ""]
    if not agg["pipelines"]:
        return "\n".join(lines + ["_Sem execuções no período._", ""])
    lines += ["| Pipeline | n | erros | latência média ms | p50 | p95 | contexto (tokens, média) | tokens gastos (média) "
              "| custo total USD | custo médio USD | acurácia | completude | fundamentação | citações |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for p in agg["pipelines"]:
        s = p["scores"]
        lines.append(f"| {p['pipeline']} | {p['n']} | {p['errors']} | {_f(p['latency_ms']['mean'])} | "
                     f"{_f(p['latency_ms']['p50'])} | {_f(p['latency_ms']['p95'])} | "
                     f"{_f(p['context_tokens']['mean'], 0)} | {_f(p['total_tokens']['mean'], 0)} | "
                     f"{_f(p['cost_usd']['total'], 6)} | {_f(p['cost_usd']['mean'], 6)} | "
                     f"{_f(s['accuracy'], 2)} | {_f(s['completeness'], 2)} | {_f(s['groundedness'], 2)} | "
                     f"{_f(s['citation_quality'], 2)} |")
    lines += ["", "Custos: somente com preço verificado; `n/d` = não disponível (nunca estimado como zero).", ""]
    return "\n".join(lines)


@router.get("/report.json")
def report_json(range: str = Query("all", pattern=RANGE_RE), session_id: str | None = None,
                include_warmup: bool = False, db: Database = Depends(get_db)) -> JSONResponse:
    return JSONResponse(build_aggregate(db, range, session_id, include_warmup),
                        headers={"Content-Disposition": 'attachment; filename="laboratorio.json"'})


@router.get("/report.md")
def report_md(range: str = Query("all", pattern=RANGE_RE), session_id: str | None = None,
              include_warmup: bool = False, db: Database = Depends(get_db)) -> PlainTextResponse:
    return PlainTextResponse(render_markdown(build_aggregate(db, range, session_id, include_warmup)),
                             media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="laboratorio.md"'})
