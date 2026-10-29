"""EXPERIMENTAL / NOT WIRED (no runtime consumer; only tests import it). ANA-184: task router PROTOTYPE, SHADOW ONLY. Maps a query to {pipeline, tier, budget} and records it; it
never acts. Verdict: HOLD (blocked by foundation: ANA-039 code tasks, ANA-186 shadow data, ANA-170 router that
discriminates). Cost of the decision is measured and must stay <= DECISION_BUDGET_MS.

Deterministic, no model, no network. The rules below are a FIRST GUESS taken from the existing difficulty
features and are not calibrated; the record carries `calibrated: False` so nobody mistakes them for evidence.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from app.routing.policy import RoutingPolicy, preset
from app.routing.router import difficulty_features, difficulty_score

DECISION_BUDGET_MS = 5.0
PIPELINES = ("fast_context", "standard", "deep")
VERDICT = "HOLD"
BLOCKED_BY = ("ANA-039", "ANA-186", "ANA-170")


@dataclass(frozen=True)
class TaskPlan:
    pipeline: str
    tier: int                 # 1-based tier index (not a registry tier id)
    budget_tokens: int
    difficulty: float
    decision_ms: float
    shadow: bool = True       # ALWAYS true: the plan is only recorded
    calibrated: bool = False
    verdict: str = VERDICT

    def to_dict(self) -> dict:
        return asdict(self)


_BUDGET = {"fast_context": 1500, "standard": 4000, "deep": 8000}


def plan_task(query: str, context_tokens: int = 0, risk: str = "low",
              policy: RoutingPolicy | None = None) -> TaskPlan:
    t0 = time.perf_counter()
    pol = policy or preset("balanced", enabled=True)
    diff = difficulty_score(difficulty_features(query, context_tokens, pol), pol)
    if diff < pol.tier_cutoffs[0] and risk == "low":
        pipe, tier = "fast_context", 1
    elif diff < pol.tier_cutoffs[-1] and risk != "high":
        pipe, tier = "standard", 2
    else:
        pipe, tier = "deep", 3
    ms = round((time.perf_counter() - t0) * 1000, 4)
    return TaskPlan(pipe, tier, _BUDGET[pipe], diff, ms)


def record_shadow(query: str, context_tokens: int = 0, risk: str = "low") -> dict:
    """The only public entry point for callers: returns a JSON-able dict to put under metrics_json
    `task_router_shadow`. It has no side effects and returns no instruction to act."""
    return plan_task(query, context_tokens, risk).to_dict()


def measure_decision_cost(queries: list[str], repeat: int = 20) -> dict:
    """Wall-clock per decision over `queries` x `repeat` (real timing on this machine)."""
    ts = []
    for _ in range(repeat):
        for q in queries:
            t0 = time.perf_counter()
            plan_task(q)
            ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    n = len(ts)
    return {"n": n, "mean_ms": round(sum(ts) / n, 4), "p95_ms": round(ts[int(0.95 * (n - 1))], 4),
            "max_ms": round(ts[-1], 4), "budget_ms": DECISION_BUDGET_MS,
            "within_budget": ts[int(0.95 * (n - 1))] <= DECISION_BUDGET_MS}
