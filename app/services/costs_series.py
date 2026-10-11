"""Hourly series and per-role aggregation for the cost ledger (pure; no I/O)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from app.services.costs import _sum_known, run_figures


def hourly_series(rows: list[dict], since: float | None, now: float | None = None) -> list[dict]:
    """[{hour:'YYYY-MM-DDTHH:00', calls, context_tokens, judge_tokens, total_tokens_spent, cost_usd}]
    ASC by hour, server local time. Zero-filled from `since` (hour-floored) to the current hour when
    `since` is given and the span is <= 31 days."""
    now = time.time() if now is None else now
    acc: dict[str, dict] = {}

    def slot(key: str) -> dict:
        return acc.setdefault(key, {"calls": 0, "context_tokens": 0, "judge_tokens": 0,
                                    "total_tokens_spent": 0, "cost": []})

    for r in rows:
        v = run_figures(r)
        d = slot(datetime.fromtimestamp(r["created_at"] or 0).strftime("%Y-%m-%dT%H:00"))
        d["calls"] += 1
        d["context_tokens"] += v["context_tokens"]["value"] or 0
        d["judge_tokens"] += v["judge_tokens"]["value"] or 0
        d["total_tokens_spent"] += v["total_tokens_spent"]["value"] or 0
        d["cost"].append(v["cost_usd"]["value"])
    if since is not None and now - since <= 31 * 86400:
        cur = datetime.fromtimestamp(since).replace(minute=0, second=0, microsecond=0)
        end = datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0)
        while cur <= end:
            slot(cur.strftime("%Y-%m-%dT%H:00"))
            cur += timedelta(hours=1)
    return [{"hour": h, "calls": d["calls"], "context_tokens": d["context_tokens"],
             "judge_tokens": d["judge_tokens"], "total_tokens_spent": d["total_tokens_spent"],
             "cost_usd": _sum_known(d["cost"]) if d["calls"] else 0.0} for h, d in sorted(acc.items())]


def roles_from_orchestration(runs: list[dict], since: float | None) -> list[dict]:
    """Aggregate orchestrator run summaries per step role (steps not pending)."""
    acc: dict[str, dict] = {}
    for run in runs:
        if since is not None and (run.get("created_at") or 0) < since:
            continue
        for st in run.get("steps") or []:
            if st.get("state") in (None, "pending"):
                continue
            a = acc.setdefault(st.get("role") or "?", {"steps": 0, "runs": set(), "tin": [], "tout": [], "cost": []})
            a["steps"] += 1
            a["runs"].add(run.get("run_id"))
            a["tin"].append(st.get("input_tokens"))
            a["tout"].append(st.get("output_tokens"))
            a["cost"].append(st.get("cost_usd"))
    out = []
    for role, a in sorted(acc.items()):
        known = [c for c in a["cost"] if c is not None]
        out.append({"role": role, "calls": a["steps"], "runs": len(a["runs"]),
                    "input_tokens": _sum_known(a["tin"]), "output_tokens": _sum_known(a["tout"]),
                    "total_tokens_spent": None, "cost_usd": _sum_known(a["cost"]),
                    "cost_status": ("unavailable" if not known
                                    else "measured" if len(known) == len(a["cost"]) else "partial")})
    return out


def roles_from_agents(rows: list[dict]) -> list[dict]:
    """Fallback: the ledger grouped by the `agent` column (key kept as `role` for the UI)."""
    acc: dict[str, dict] = {}
    for r in rows:
        v = run_figures(r)
        a = acc.setdefault(r.get("agent") or "?", {"calls": 0, "tokens": [], "cost": []})
        a["calls"] += 1
        a["tokens"].append(v["total_tokens_spent"]["value"])
        a["cost"].append(v["cost_usd"]["value"])
    return [{"role": k, "calls": a["calls"], "runs": a["calls"], "input_tokens": None, "output_tokens": None,
             "total_tokens_spent": _sum_known(a["tokens"]), "cost_usd": _sum_known(a["cost"]),
             "cost_status": "measured" if any(c is not None for c in a["cost"]) else "unavailable"}
            for k, a in sorted(acc.items())]
