"""Pure read-only helpers behind the Onda 7 dashboard endpoints (ANA-202, ANA-210, ANA-213).

No I/O here: callers pass already-loaded runs / notes. Nothing is invented — a figure that cannot be
computed from stored data is `None` and the UI renders it as "indisponível".
"""
from __future__ import annotations

import math
import statistics as st
from typing import Any, Iterable

DEFAULT_THRESHOLDS = {"tokens_pct": 20.0, "latency_p95_pct": 25.0, "cost_pct": 25.0}
MIN_RUNS = 5
METRICS = (  # (alert metric, run-metric key, aggregate)
    ("context_tokens", "context_tokens", "mean"),
    ("latency_p95_ms", "total_latency_ms", "p95"),
    ("cost_usd", "total_cost", "mean"),
)
_THRESHOLD_FOR = {"context_tokens": "tokens_pct", "latency_p95_ms": "latency_p95_pct", "cost_usd": "cost_pct"}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _agg(values: Iterable[float], how: str) -> float | None:
    v = sorted(values)
    if not v:
        return None
    if how == "p95":
        return v[max(0, math.ceil(0.95 * len(v)) - 1)]
    return st.fmean(v)


def _run_cost(m: dict) -> float | None:
    """Money of one run from its own metrics; only counted when the run reports it."""
    return _num(m.get("total_cost")) if m.get("total_cost") is not None else _num(m.get("jev_cost"))


def regression_alerts(runs: list[dict], *, window: int = 20, thresholds: dict | None = None) -> dict:
    """Compare, per pipeline, the newest `window` runs against the `window` before them.

    `runs` must be newest-first. Warm-up runs and runs with an error are ignored. A pipeline with fewer
    than MIN_RUNS runs in either window is reported under `insufficient`, never as "ok".
    Recall is NOT evaluated: it is not stored per run (only the labelled sweep computes it).
    """
    th = {**DEFAULT_THRESHOLDS, **{k: float(v) for k, v in (thresholds or {}).items() if k in DEFAULT_THRESHOLDS}}
    window = max(MIN_RUNS, int(window))
    by_pipe: dict[str, list[dict]] = {}
    for r in runs:
        if r.get("warmup") or r.get("error"):
            continue
        by_pipe.setdefault(r.get("pipeline") or "-", []).append(r)
    alerts: list[dict] = []
    evaluated: list[str] = []
    insufficient: list[dict] = []
    for pipe, rs in sorted(by_pipe.items()):
        cur, base = rs[:window], rs[window:2 * window]
        if len(cur) < MIN_RUNS or len(base) < MIN_RUNS:
            insufficient.append({"pipeline": pipe, "runs": len(rs), "needed": 2 * MIN_RUNS})
            continue
        evaluated.append(pipe)
        for name, key, how in METRICS:
            def series(group: list[dict]) -> list[float]:
                out = []
                for r in group:
                    m = r.get("metrics") or {}
                    v = _run_cost(m) if key == "total_cost" else _num(m.get(key))
                    if v is not None:
                        out.append(v)
                return out
            b_s, c_s = series(base), series(cur)
            if len(b_s) < MIN_RUNS or len(c_s) < MIN_RUNS:
                continue
            b, c = _agg(b_s, how), _agg(c_s, how)
            if b is None or c is None or b <= 0:
                continue
            change = (c - b) / b * 100.0
            limit = th[_THRESHOLD_FOR[name]]
            if change > limit:
                alerts.append({"pipeline": pipe, "metric": name, "baseline": round(b, 6), "current": round(c, 6),
                               "change_pct": round(change, 2), "threshold_pct": limit,
                               "severity": "critical" if change > 2 * limit else "warning",
                               "n_baseline": len(b_s), "n_current": len(c_s)})
    return {"alerts": alerts, "count": len(alerts), "evaluated": evaluated, "insufficient": insufficient,
            "thresholds": th, "window": window, "recall_evaluated": False}


def provider_health(runs: list[dict], integrations: list[dict] | None = None, *, last_n: int = 100,
                    keys: dict[str, bool] | None = None) -> dict:
    """Per-provider health from the last `last_n` recorded calls (no probe, no paid call).

    Providers come from the runs' `provider` (consumer model) — runs with no provider are grouped under
    `agent` so the table never silently drops traffic. `integrations` (detect_all agents) are merged in
    as availability only. `key_present` is None when unknown (never guessed).
    """
    groups: dict[str, list[dict]] = {}
    for r in runs[:max(1, last_n)]:
        name = r.get("provider") or (f"agent:{r['agent']}" if r.get("agent") else "gateway")
        groups.setdefault(name, []).append(r)
    rows = []
    for name, rs in sorted(groups.items()):
        lats = [v for v in (_num((r.get("metrics") or {}).get("total_latency_ms")) for r in rs) if v is not None]
        errs = sum(1 for r in rs if r.get("error"))
        rows.append({"provider": name, "calls": len(rs), "errors": errs,
                     "error_rate": round(errs / len(rs), 4),
                     "latency_p50_ms": round(st.median(lats), 2) if lats else None,
                     "latency_p95_ms": round(_agg(lats, "p95"), 2) if lats else None,
                     "last_call_at": max((r.get("created_at") or 0) for r in rs) or None,
                     "key_present": (keys or {}).get(name),
                     "source": "ledger"})
    agents = [{"agent": a.get("agent"), "available": bool(a.get("available")), "metrics": a.get("metrics"),
               "reason": a.get("reason")} for a in (integrations or [])]
    return {"window": last_n, "providers": rows, "agents": agents, "probe": False,
            "note": "taxa de erro das últimas chamadas gravadas; nenhuma chamada paga é feita"}


def _norm(path: Any) -> str:
    return str(path or "").replace("\\", "/").strip().lower()


def memory_lineage(notes: list[dict], runs: list[dict], *, max_runs_per_note: int = 10) -> dict:
    """note -> (source_agent, project, source, created) and the runs whose delivered sources cite it.

    A run "cites" a note when one of its sources' `file` equals the note's file or ends with it.
    Origin fields come from the note's own front matter; a missing one stays None (never inferred).
    """
    cited: dict[str, list[dict]] = {}
    index = {_norm(n.get("file")): n for n in notes if n.get("file")}
    for r in runs:
        seen: set[str] = set()
        for s in r.get("sources") or []:
            f = _norm(s.get("file"))
            if not f:
                continue
            for nf in index:
                if f == nf or f.endswith("/" + nf) or nf.endswith("/" + f):
                    if nf not in seen:
                        seen.add(nf)
                        cited.setdefault(nf, []).append({"run_id": r.get("run_id"), "created_at": r.get("created_at"),
                                                         "pipeline": r.get("pipeline"), "agent": r.get("agent")})
    items = []
    for n in notes:
        c = cited.get(_norm(n.get("file")), [])
        items.append({"id": n.get("id"), "title": n.get("title"), "project": n.get("project"),
                      "source_agent": n.get("source_agent"), "source": n.get("source"), "created": n.get("created"),
                      "kind": n.get("kind"), "status": n.get("status"), "supersedes": n.get("supersedes"),
                      "superseded_by": n.get("superseded_by"),
                      "has_origin": bool(n.get("source_agent") or (n.get("source") not in (None, "", "manual"))),
                      "cited_by_count": len(c), "cited_by": c[:max_runs_per_note]})
    with_origin = sum(1 for i in items if i["has_origin"])
    return {"count": len(items), "with_origin": with_origin,
            "origin_coverage": round(with_origin / len(items), 4) if items else None, "notes": items}
