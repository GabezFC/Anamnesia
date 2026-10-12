"""ANA-023: the judge's safety-net fallback is a FAILURE SIGNAL, not a normal outcome.

When the judge drops every candidate (or is unavailable) the pipelines deliver the top retrieval candidates
anyway (`jev_fallback_used`). That keeps answers non-empty but hides that the judge produced nothing useful.
This module turns the per-run counters into `fallback_rate` per pipeline and ISO week, with a Wilson CI and
an alarm when the rate is above `ALARM_THRESHOLD` over the window (needs `MIN_RUNS` judged runs).
Pure functions over the run rows; no I/O.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

ALARM_THRESHOLD = 0.10
MIN_RUNS = 10


def is_fallback_decision(decision: str | None) -> bool:
    return bool(decision) and str(decision).upper().endswith("FALLBACK")


def run_flags(metrics: dict | None) -> tuple[bool, bool]:
    """(judged_run, fallback_run) for one run's metrics. A run is 'judged' if a JEV pipeline ran it."""
    m = metrics or {}
    judged = m.get("jev_mode") is not None or m.get("jev_fallback_used") is not None \
        or m.get("judge_fallback") is not None
    fb = bool(m.get("judge_fallback")) or bool((m.get("jev_fallback_used") or 0) > 0)
    return judged, fb


def _week(ts: float | None) -> str:
    if not ts:
        return "unknown"
    y, w, _ = datetime.fromtimestamp(float(ts), tz=timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def fallback_report(runs: Iterable[dict], threshold: float = ALARM_THRESHOLD, min_runs: int = MIN_RUNS) -> dict:
    from app.benchmark.statistics import wilson_ci
    cells: dict[tuple[str, str], list[int]] = {}
    for r in runs:
        if r.get("warmup"):
            continue
        judged, fb = run_flags(r.get("metrics"))
        if not judged:
            continue
        k = (r.get("pipeline") or "?", _week(r.get("created_at")))
        c = cells.setdefault(k, [0, 0])
        c[0] += 1
        c[1] += int(fb)
    rows = []
    tot_n = tot_k = 0
    for (pipe, week), (n, k) in sorted(cells.items()):
        ci = wilson_ci(k, n)
        rows.append({"pipeline": pipe, "week": week, "runs": n, "fallback_runs": k,
                     "fallback_rate": ci["rate"], "ci95": [ci["low"], ci["high"]],
                     "alarm": n >= min_runs and (ci["rate"] or 0) > threshold})
        tot_n += n
        tot_k += k
    overall = wilson_ci(tot_k, tot_n)
    return {"threshold": threshold, "min_runs": min_runs, "runs_judged": tot_n, "fallback_runs": tot_k,
            "fallback_rate": overall["rate"], "ci95": [overall["low"], overall["high"]],
            "alarm": tot_n >= min_runs and (overall["rate"] or 0) > threshold, "by_pipeline_week": rows}
