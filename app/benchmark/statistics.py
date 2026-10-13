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
    try:  # ANA-023: judge fallback_rate per pipeline/week + alarm
        from app.services.judge_health import fallback_report
        s["judge_health"] = fallback_report(runs)
    except Exception:  # noqa: BLE001 -- reporting must never break the stats endpoint
        s["judge_health"] = None
    return s


# ---------------------------------------------------------------------------------------------
# ANA-013 / ANA-014: confidence intervals, paired comparison and sample size.
# Pure stdlib, deterministic (explicit seed). A rate without its interval must not be quoted.
# ---------------------------------------------------------------------------------------------
import random as _random

from app.core.stats import _Z95, bootstrap_ci, paired_diff_ci, wilson_ci  # noqa: E402,F401  (live in core: routing may use them)


def mcnemar_exact(a_ok: Iterable[bool], b_ok: Iterable[bool]) -> dict:
    """Exact two-sided McNemar test on paired binary outcomes (A vs B)."""
    only_a = only_b = 0
    for x, y in zip(a_ok, b_ok):
        only_a += bool(x) and not y
        only_b += bool(y) and not x
    n = only_a + only_b
    if n == 0:
        return {"only_a": 0, "only_b": 0, "p_value": 1.0}
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {"only_a": only_a, "only_b": only_b, "p_value": round(min(1.0, 2 * tail), 6)}


def required_n_two_proportions(p1: float, delta: float, power: float = 0.8, alpha: float = 0.05) -> int:
    """Per-arm n to detect a difference `delta` from baseline rate p1 (two-sided normal approximation)."""
    if not 0 < delta < 1:
        raise ValueError("delta must be in (0,1)")
    p2 = min(max(p1 + delta, 0.0), 1.0)
    nd = st.NormalDist()
    za, zb = nd.inv_cdf(1 - alpha / 2), nd.inv_cdf(power)
    pbar = (p1 + p2) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return max(2, math.ceil(num / (p2 - p1) ** 2))


def achieved_power(n: int, p1: float, delta: float, alpha: float = 0.05) -> float:
    """Power of a two-proportion test with `n` per arm (normal approximation)."""
    p2 = min(max(p1 + delta, 0.0), 1.0)
    if n < 2 or p2 == p1:
        return 0.0
    nd = st.NormalDist()
    za = nd.inv_cdf(1 - alpha / 2)
    pbar = (p1 + p2) / 2
    se0 = math.sqrt(2 * pbar * (1 - pbar) / n)
    se1 = math.sqrt((p1 * (1 - p1) + p2 * (1 - p2)) / n)
    return round(nd.cdf((abs(p2 - p1) - za * se0) / se1), 4)


def power_report(n: int, p1: float = 0.5, delta: float = 0.10) -> dict:
    need = required_n_two_proportions(p1, delta)
    return {"n": n, "baseline_rate": p1, "min_detectable_delta": delta, "required_n_per_arm": need,
            "achieved_power": achieved_power(n, p1, delta), "sufficient": n >= need}
