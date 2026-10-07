"""Per-call cost ledger: pure aggregation over `runs` rows (no I/O, no DB, no network).

Every token/cost figure is a labelled value {"value": x, "origin": "measured|estimated|unavailable"}.
Money is only reported when the model price is verified (config.pricing.price_status); otherwise
it is None -- never a guessed number.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from config.pricing import price_status

MEASURED, ESTIMATED, UNAVAILABLE = "measured", "estimated", "unavailable"
RANGES = ("today", "7d", "30d", "all")
BUDGET_PERIODS = ("day", "month")
WARN_RATIO = 0.8


def lv(value: Any, origin: str) -> dict:
    """Labelled value; a missing value is always origin 'unavailable'."""
    if value is None:
        return {"value": None, "origin": UNAVAILABLE}
    return {"value": value, "origin": origin}


def project_from_scope(scope: str | None) -> str | None:
    """'projeto:a,projeto:b,area:x' -> 'a,b'; global / area-only / empty -> None."""
    if not scope:
        return None
    projs = [p[len("projeto:"):] for p in str(scope).split(",") if p.startswith("projeto:")]
    return ",".join(projs) or None


def _is_jev(pipeline: str | None) -> bool:
    return bool(pipeline) and "jev" in pipeline


def cost_origin_for(metrics: dict, pipeline: str | None = None) -> str:
    """Overall origin of a call's token figures: measured when the judge's usage was reported,
    estimated when only our own estimator figures exist, unavailable otherwise."""
    pipeline = pipeline or metrics.get("pipeline")
    if _is_jev(pipeline) and metrics.get("jev_input_tokens") is not None:
        return MEASURED
    if metrics.get("context_tokens") is not None:
        return ESTIMATED
    return UNAVAILABLE


def _metrics(row: dict) -> dict:
    m = row.get("metrics_json")
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            return {}
    return m if isinstance(m, dict) else {}


def run_figures(row: dict) -> dict:
    """Labelled figures of one run row (tokens, money, latency, cache)."""
    m = _metrics(row)
    jev = _is_jev(row.get("pipeline"))
    if jev:
        ps = price_status(row.get("jev_model"))
        judge = lv(m.get("judge_tokens") if m.get("jev_input_tokens") is not None else None, MEASURED)
        jc = m.get("jev_cost")
        money = jc if (ps["status"] != "unavailable" and jc is not None) else None
    else:
        # no model API was called by the gateway itself: judge tokens and API money are a true 0
        ps = {"status": "not_applicable"}
        judge = lv(0, MEASURED)
        money = 0.0
    cache = m.get("result_cache_hit")
    return {
        "candidate_tokens": lv(m.get("candidate_tokens_before_filter"), ESTIMATED),
        "context_tokens": lv(m.get("context_tokens"), ESTIMATED),
        "judge_tokens": judge,
        "total_tokens_spent": lv(m.get("total_tokens_spent"), ESTIMATED),
        "cost_usd": lv(money, MEASURED),
        "price_status": ps["status"],
        "latency_ms": lv(m.get("total_latency_ms"), MEASURED),
        "cache_hit": lv(None if cache is None else bool(cache), MEASURED),
        "context_reduction": lv(m.get("context_reduction"), ESTIMATED),
    }


def call_view(row: dict, metrics_only: bool = False) -> dict:
    m = _metrics(row)
    out = {
        "run_id": row["run_id"], "created_at": row.get("created_at"),
        "project": row.get("project"), "terminal_session_id": row.get("terminal_session_id"),
        "agent": row.get("agent"), "client": m.get("client"),
        "pipeline": row.get("pipeline"), "mode": row.get("mode"),
        "model": row.get("model"), "jev_model": row.get("jev_model"),
        "cost_origin": row.get("cost_origin") or cost_origin_for(m, row.get("pipeline")),
        "error": bool(row.get("error")),
    }
    out.update(run_figures(row))
    if not metrics_only:
        out["query"] = row.get("query")
    return out


def range_since(rng: str, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    if rng == "all":
        return None
    if rng == "today":
        d = datetime.fromtimestamp(now)
        return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return now - {"7d": 7, "30d": 30}[rng] * 86400


def _sum_known(vals: list) -> float | None:
    known = [v for v in vals if v is not None]
    return round(sum(known), 8) if known else None


def budget_status(spent: float | None, ceiling: float | None) -> dict:
    """ok | warn (>=80%) | exceeded (>=100%). Unknown spend or no ceiling never raises an alarm."""
    if ceiling is None or ceiling <= 0 or spent is None:
        return {"status": "ok", "ceiling_usd": ceiling, "spent_usd": spent, "ratio": None}
    ratio = spent / ceiling
    st = "exceeded" if ratio >= 1 else "warn" if ratio >= WARN_RATIO else "ok"
    return {"status": st, "ceiling_usd": ceiling, "spent_usd": spent, "ratio": round(ratio, 4)}


def summarize(rows: list[dict], rng: str = "all", budgets: dict | None = None,
              spent_day: float | None = None, spent_month: float | None = None) -> dict:
    views = [call_view(r, metrics_only=True) for r in rows]

    def tot(key: str, origin: str) -> dict:
        known = [v[key] for v in views if v[key]["value"] is not None]
        if not known:
            return lv(None, origin)
        # a total is 'measured' only if every contributing figure is; one estimate demotes it
        all_measured = all(k["origin"] == MEASURED for k in known)
        return lv(sum(k["value"] for k in known), MEASURED if all_measured else origin)

    priced = [v["cost_usd"]["value"] for v in views if v["cost_usd"]["value"] is not None]
    by_day: dict[str, dict] = {}
    by_pipeline: dict[str, int] = {}
    for r, v in zip(rows, views):
        day = datetime.fromtimestamp(r["created_at"] or 0).strftime("%Y-%m-%d")
        d = by_day.setdefault(day, {"calls": 0, "context_tokens": 0, "judge_tokens": 0, "cost": []})
        d["calls"] += 1
        d["context_tokens"] += v["context_tokens"]["value"] or 0
        d["judge_tokens"] += v["judge_tokens"]["value"] or 0
        d["cost"].append(v["cost_usd"]["value"])
        key = v["pipeline"] or "?"
        by_pipeline[key] = by_pipeline.get(key, 0) + 1
    series = [{"day": day, "calls": d["calls"], "context_tokens": d["context_tokens"],
               "judge_tokens": d["judge_tokens"], "cost_usd": _sum_known(d["cost"])}
              for day, d in sorted(by_day.items())]
    budgets = budgets or {}
    return {
        "range": rng,
        "calls": len(rows),
        "priced_calls": len(priced),
        "candidate_tokens": tot("candidate_tokens", ESTIMATED),
        "context_tokens": tot("context_tokens", ESTIMATED),
        "judge_tokens": tot("judge_tokens", MEASURED),
        "total_tokens_spent": tot("total_tokens_spent", ESTIMATED),
        "cost_usd": lv(_sum_known(priced), MEASURED),
        "cache_hits": sum(1 for v in views if v["cache_hit"]["value"]),
        "by_pipeline": by_pipeline,
        "series": series,
        "budget": {"day": budget_status(spent_day, budgets.get("day")),
                   "month": budget_status(spent_month, budgets.get("month"))},
    }


def spend_of(rows: list[dict]) -> float | None:
    return _sum_known([run_figures(r)["cost_usd"]["value"] for r in rows])


CSV_FIELDS = ["run_id", "created_at", "project", "terminal_session_id", "agent", "pipeline", "mode",
              "model", "cost_origin", "candidate_tokens", "candidate_tokens_origin", "context_tokens",
              "context_tokens_origin", "judge_tokens", "judge_tokens_origin", "cost_usd", "cost_usd_origin",
              "price_status", "latency_ms", "cache_hit"]


def csv_row(view: dict, metrics_only: bool = False) -> dict:
    out = {k: view.get(k) for k in CSV_FIELDS if k in view and not isinstance(view.get(k), dict)}
    for k in ("candidate_tokens", "context_tokens", "judge_tokens", "cost_usd"):
        out[k] = view[k]["value"]
        out[k + "_origin"] = view[k]["origin"]
    out["latency_ms"] = view["latency_ms"]["value"]
    out["cache_hit"] = view["cache_hit"]["value"]
    if not metrics_only:
        out["query"] = view.get("query")
    return out
