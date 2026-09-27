"""Statistics (§49, §60–§68, §89). Pure functions over stored runs."""
from __future__ import annotations

import math
import statistics as st
from typing import Iterable


def describe(values: Iterable[float | None]) -> dict:
    v = sorted(x for x in values if x is not None)
    if not v:
        return {"n": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None, "std": None}
    k = max(0, math.ceil(0.95 * len(v)) - 1)
    return {"n": len(v), "mean": round(st.fmean(v), 3), "median": round(st.median(v), 3), "p95": round(v[k], 3),
            "min": round(v[0], 3), "max": round(v[-1], 3), "std": round(st.stdev(v), 3) if len(v) > 1 else 0.0}


METRIC_KEYS = ("total_latency_ms", "retrieval_latency_ms", "filter_latency_ms", "generation_latency_ms",
               "documents_found", "documents_sent_to_model", "candidate_tokens_before_filter", "context_tokens",
               "context_reduction", "jev_input_tokens", "jev_latency_ms", "jev_cost", "model_input_tokens",
               "model_output_tokens", "agent_tokens", "model_cost", "total_cost")


def summarize(runs: list[dict]) -> dict:
    """Group by (agent, provider, model, pipeline) and describe each metric. Warm-up runs are excluded."""
    groups: dict[tuple, list[dict]] = {}
    for r in runs:
        if r.get("warmup"):
            continue
        key = (r.get("agent") or "-", r.get("provider") or "-", r.get("model") or "-", r["pipeline"])
        groups.setdefault(key, []).append(r.get("metrics") or {})
    out = []
    for (agent, provider, model, pipeline), ms in sorted(groups.items()):
        row = {"agent": agent, "provider": provider, "model": model, "pipeline": pipeline, "runs": len(ms)}
        for k in METRIC_KEYS:
            row[k] = describe(m.get(k) for m in ms)
        out.append(row)
    return {"groups": out}


def aggregate_stats(db, session_id: str | None = None) -> dict:
    runs = db.list_runs(limit=100000, session_id=session_id)
    s = summarize(runs)
    s["total_runs"] = len(runs)
    s["sessions"] = len(db.list_sessions(limit=100000))
    s["false_negatives"] = db.false_negative_rate()
    return s
