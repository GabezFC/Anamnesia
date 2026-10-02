"""Server-side time series over ALL runs (M1). Mirrors the metric derivations of frontend/js/format.js.

Pipeline (order matters, each step is covered by tests/test_timeseries.py):
    validate timestamp -> normalise (ms -> s, ISO 8601 -> epoch) -> drop invalid (counted)
    -> sort ASC -> dedup run_id -> aggregate (median + p25/p75 + n) -> downsample (only AFTER sorting)

Nothing here estimates a value: a metric the run does not carry is skipped, never plotted as 0.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

MS_THRESHOLD = 1e12          # epoch seconds stay < 1e12 until the year ~33658; ms values are above it
AGGS = ("day", "session", "run")
DEFAULT_MAX_POINTS = 600
MAX_POINTS_CEILING = 5000


# -- timestamps ------------------------------------------------------------------------------
def normalize_ts(value: Any) -> float | None:
    """Epoch seconds from epoch s, epoch ms or ISO 8601 (with/without Z or offset; naive = UTC).

    Returns None for null, non-numeric garbage, NaN/inf, booleans and non-positive values.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return _parse_iso(text)
    if not isinstance(value, (int, float)):
        return None
    x = float(value)
    if not math.isfinite(x) or x <= 0:
        return None
    if x > MS_THRESHOLD:
        x /= 1000.0
    return x


def _parse_iso(text: str) -> float | None:
    if text[-1] in "zZ":
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = dt.timestamp()
    return ts if ts > 0 else None


def day_key(ts: float, utc: bool = False) -> str:
    """Calendar day (YYYY-MM-DD) of an epoch-seconds value; local server time unless `utc`."""
    dt = datetime.fromtimestamp(ts, timezone.utc) if utc else datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d")


# -- metric extraction (same derivation as format.js) ------------------------------------------
def _get(obj: Any, path: str) -> Any:
    cur = obj
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def _sum_present(values: Iterable[Any]) -> float | None:
    parts = [n for n in (_num(v) for v in values) if n is not None]
    return sum(parts) if parts else None


def judge_tokens(m: dict) -> float | None:
    direct = _num(_get(m, "judge_tokens"))
    if direct is not None:
        return direct
    return _sum_present([_get(m, "jev_input_tokens"), _get(m, "jev_output_tokens")])


def total_tokens(m: dict) -> float | None:
    direct = _num(_get(m, "total_tokens_spent"))
    if direct is not None:
        return direct
    return _sum_present([judge_tokens(m), _get(m, "context_tokens")])


def token_amplification(m: dict) -> float | None:
    direct = _num(_get(m, "token_amplification"))
    if direct is not None:
        return direct
    tot, ctx = total_tokens(m), _num(_get(m, "context_tokens"))
    return tot / ctx if tot is not None and ctx else None


def saved_tokens(m: dict) -> float | None:
    return _sum_present(_get(m, k) for k in
                        ("prefilter_tokens_saved_estimate", "dedup_near_tokens_saved_estimate",
                         "snippet_tokens_saved"))


def cost_of(m: dict) -> float | None:
    t = _num(_get(m, "total_cost"))
    if t is not None:
        return t
    mc, jc = _num(_get(m, "model_cost")), _num(_get(m, "jev_cost"))
    if mc is None and jc is None:
        return None
    return (mc or 0.0) + (jc or 0.0)


def recall_of(m: dict) -> float | None:
    return _num(_get(m, "expected_sources_found.recall"))


def precision_of(m: dict) -> float | None:
    found, sent = _num(_get(m, "expected_sources_found.found")), _num(_get(m, "documents_sent_to_model"))
    if found is None or sent is None or sent <= 0:
        return None
    return min(1.0, found / sent)


# Same keys as HIST_SERIES in frontend/js/pages-data.js.
METRICS: dict[str, Callable[[dict], float | None]] = {
    "tokens": total_tokens,
    "judge": judge_tokens,
    "context": lambda m: _num(_get(m, "context_tokens")),
    "saved": saved_tokens,
    "amplification": token_amplification,
    "latency": lambda m: _num(_get(m, "total_latency_ms")),
    "cost": cost_of,
    "documents": lambda m: _num(_get(m, "documents_sent_to_model")),
    "recall": recall_of,
    "precision": precision_of,
}


# -- statistics ------------------------------------------------------------------------------
def quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted, non-empty list."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def lttb(points: list[dict], threshold: int) -> list[dict]:
    """Largest-Triangle-Three-Buckets on points ordered by `x` (threshold >= 3). Keeps real points
    (timestamp->value pairs are never interpolated), keeps first and last, preserves ASC order."""
    n = len(points)
    if threshold >= n:
        return points[:]
    sampled = [points[0]]
    every = (n - 2) / (threshold - 2)
    a = 0
    for i in range(threshold - 2):
        start = int(math.floor(i * every)) + 1
        end = int(math.floor((i + 1) * every)) + 1
        nxt = points[end:min(int(math.floor((i + 2) * every)) + 1, n)] or [points[-1]]
        avg_x = sum(p["x"] for p in nxt) / len(nxt)
        avg_y = sum(p["y"] for p in nxt) / len(nxt)
        ax, ay = points[a]["x"], points[a]["y"]
        best, best_area = start, -1.0
        for j in range(start, end):
            area = abs((ax - avg_x) * (points[j]["y"] - ay) - (ax - points[j]["x"]) * (avg_y - ay))
            if area > best_area:
                best, best_area = j, area
        sampled.append(points[best])
        a = best
    sampled.append(points[-1])
    return sampled


# -- aggregation -----------------------------------------------------------------------------
def _stats(ys: list[float]) -> dict:
    s = sorted(ys)
    return {"y": quantile(s, 0.5), "p25": quantile(s, 0.25), "p75": quantile(s, 0.75), "n": len(s)}


def _parse_metrics(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def build_series(rows: Iterable[dict], metric: str, agg: str = "day", since: Any = None, until: Any = None,
                 max_points: int = DEFAULT_MAX_POINTS, utc: bool = False) -> dict:
    """Series for ONE group of runs (the caller splits by pipeline). `rows` need run_id, session_id,
    created_at and metrics_json (str or dict). Warm-up filtering is the caller's job."""
    if metric not in METRICS:
        raise ValueError(f"métrica desconhecida: {metric!r} (válidas: {', '.join(METRICS)})")
    if agg not in AGGS:
        raise ValueError(f"agg inválido: {agg!r} (válidos: {', '.join(AGGS)})")
    max_points = max(3, min(int(max_points), MAX_POINTS_CEILING))
    lo = normalize_ts(since) if since not in (None, "") else None
    hi = normalize_ts(until) if until not in (None, "") else None
    if since not in (None, "") and lo is None:
        raise ValueError(f"since inválido: {since!r}")
    if until not in (None, "") and hi is None:
        raise ValueError(f"until inválido: {until!r}")

    invalid = 0
    valid: list[tuple[float, dict]] = []
    for r in rows:
        ts = normalize_ts(r.get("created_at"))
        if ts is None:
            invalid += 1
            continue
        valid.append((ts, r))
    valid.sort(key=lambda t: t[0])                       # ASC before anything else

    seen: set = set()
    in_range = 0
    metric_fn = METRICS[metric]
    recs: list[dict] = []
    for ts, r in valid:
        rid = r.get("run_id")
        if rid is not None:
            if rid in seen:
                continue
            seen.add(rid)
        if (lo is not None and ts < lo) or (hi is not None and ts > hi):
            continue
        in_range += 1
        y = metric_fn(_parse_metrics(r.get("metrics_json", r.get("metrics"))))
        if y is None:
            continue                                     # a hole is a hole, never 0
        recs.append({"x": ts, "y": y, "session": str(r.get("session_id") or "adhoc")})

    if agg == "run":
        points = [{"x": p["x"], "y": p["y"], "n": 1, "p25": p["y"], "p75": p["y"], "bucket": p["session"]}
                  for p in recs]
    else:
        groups: dict[str, list[dict]] = {}
        for p in recs:                                   # recs is ASC, dict keeps first-seen order
            key = p["session"] if agg == "session" else day_key(p["x"], utc)
            groups.setdefault(key, []).append(p)
        points = []
        for key, g in groups.items():
            st = _stats([p["y"] for p in g])
            xs = sorted(p["x"] for p in g)
            points.append({"x": quantile(xs, 0.5), **st, "bucket": key,
                           **({"day": key} if agg == "day" else {}), "sessions": len({p["session"] for p in g})})
        points.sort(key=lambda p: p["x"])                # session groups can interleave: re-sort by time

    sampled = len(points) > max_points
    if sampled:
        points = lttb(points, max_points)
    return {
        "points": points,
        "total_runs_in_range": in_range,
        "runs_with_metric": len(recs),
        "points_returned": len(points),
        "sampled": sampled,
        "invalid_dropped": invalid,
        "range": {"first": recs[0]["x"] if recs else None, "last": recs[-1]["x"] if recs else None},
    }


def build_timeseries(rows: Iterable[dict], metric: str, agg: str = "day", since: Any = None, until: Any = None,
                     max_points: int = DEFAULT_MAX_POINTS, utc: bool = False) -> dict:
    """Full response: one series per pipeline plus overall metadata."""
    by_pipeline: dict[str, list[dict]] = {}
    for r in rows:
        by_pipeline.setdefault(str(r.get("pipeline") or "?"), []).append(r)
    series = {p: build_series(rs, metric, agg, since, until, max_points, utc) for p, rs in sorted(by_pipeline.items())}
    firsts = [s["range"]["first"] for s in series.values() if s["range"]["first"] is not None]
    lasts = [s["range"]["last"] for s in series.values() if s["range"]["last"] is not None]
    return {
        "metric": metric, "agg": agg, "timezone": "utc" if utc else "local",
        "series": series,
        "total_runs_in_range": sum(s["total_runs_in_range"] for s in series.values()),
        "points_returned": sum(s["points_returned"] for s in series.values()),
        "sampled": any(s["sampled"] for s in series.values()),
        "invalid_dropped": sum(s["invalid_dropped"] for s in series.values()),
        "max_points": max(3, min(int(max_points), MAX_POINTS_CEILING)),
        "range": {"first": min(firsts) if firsts else None, "last": max(lasts) if lasts else None},
    }
