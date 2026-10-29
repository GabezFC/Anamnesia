"""Opt-in economy rules driven by persisted settings (app/services/settings_store.py).

Everything here is inert unless the user turned it on (all three settings default to off/None), so
the default behaviour of search() is byte-for-byte what it was before. Pure functions, zero model
calls.

1. auto_graphify_jev_opt  -- let `auto` pick the paid `graphify_jev_opt` when it pays for itself.
   HEURISTIC (`should_use_jev_opt`): the paid judge is only worth it when ALL hold
     a) the router would otherwise send the query to the free baseline (we never override an
        explicit route configured through MG_ROUTE_*, nor an explicit pipeline);
     b) the query is hard for lexical recall: complexity COMPLEX, or AMBIGUOUS with a multi-hop hint
        (SIMPLE/MEDIUM are answered at the top of baseline; see Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24/reports/SCOPE_BENCHMARK.md));
     c) the cheap lexical pool is big enough that filtering saves context: size_estimate
        >= JEV_MIN_POOL (30). With a small pool there is nothing to filter and the judge would cost
        more tokens than it removes. Unknown size -> stay on baseline;
     d) the estimated judge cost (pool * JUDGE_TOKENS_PER_CANDIDATE) fits max_tokens_per_query when a
        cap is set (otherwise the judge alone could blow the user's ceiling).
2. max_tokens_per_query   -- ceiling for the context budget of any search (min with the requested one).
3. reduce_max_results_by_question_type -- scale max_results by question type, `auto` only:
   SIMPLE (short/factual) x0.5 (floor 3); MEDIUM unchanged; COMPLEX/AMBIGUOUS x1.5 (cap 50).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

JEV_MIN_POOL = 30
JUDGE_TOKENS_PER_CANDIDATE = 150
MIN_RESULTS = 3
MAX_RESULTS = 50
SHRINK = 0.5
GROW = 1.5


@dataclass(frozen=True)
class EconomySettings:
    auto_graphify_jev_opt: bool = False
    reduce_max_results_by_question_type: bool = False
    max_tokens_per_query: int | None = None

    @property
    def active(self) -> bool:
        return bool(self.auto_graphify_jev_opt or self.reduce_max_results_by_question_type
                    or self.max_tokens_per_query)


def should_use_jev_opt(complexity: str, multi_hop_hint: bool, size_estimate: int | None,
                       max_tokens: int | None = None) -> tuple[bool, str]:
    hard = complexity == "COMPLEX" or (complexity == "AMBIGUOUS" and multi_hop_hint)
    if not hard:
        return False, f"not_hard:{complexity}"
    if size_estimate is None:
        return False, "pool_unknown"
    if size_estimate < JEV_MIN_POOL:
        return False, f"pool_small:{size_estimate}"
    judge = size_estimate * JUDGE_TOKENS_PER_CANDIDATE
    if max_tokens is not None and judge > max_tokens:
        return False, f"judge_over_cap:{judge}>{max_tokens}"
    return True, f"hard_pool:{complexity}:{size_estimate}"


def scale_max_results(complexity: str, max_results: int) -> int:
    if complexity == "SIMPLE":
        return max(min(MIN_RESULTS, max_results), math.ceil(max_results * SHRINK))
    if complexity in ("COMPLEX", "AMBIGUOUS"):
        return min(MAX_RESULTS, max(max_results, math.ceil(max_results * GROW)))
    return max_results


def apply_economy(eco: EconomySettings, plan, max_results: int, context_budget: int | None,
                  default_budget: int, size_probe) -> tuple[Any, int, int | None, dict]:
    """Return (plan, max_results, context_budget, metrics). `size_probe()` -> candidate count|None,
    only called when the jev_opt rule needs it. `plan` is replaced, never mutated."""
    m: dict[str, Any] = {}
    if not eco.active:
        return plan, max_results, context_budget, m
    is_auto = plan.requested == "auto"
    profile = plan.profile
    complexity = profile.complexity if profile else "AMBIGUOUS"
    if is_auto and eco.auto_graphify_jev_opt and plan.pipeline == "baseline":
        size = size_probe()
        ok, why = should_use_jev_opt(complexity, bool(profile and profile.multi_hop_hint), size,
                                     eco.max_tokens_per_query)
        m["economy_jev_opt"] = why
        if ok:
            plan = replace(plan, pipeline="graphify_jev_opt", reason=f"economy:{why}",
                           verdict_size_estimate=size)
    if is_auto and eco.reduce_max_results_by_question_type:
        new = scale_max_results(complexity, max_results)
        if new != max_results:
            m["economy_max_results"] = {"from": max_results, "to": new, "type": complexity}
            max_results = new
    if eco.max_tokens_per_query:
        base = context_budget or default_budget
        if base > eco.max_tokens_per_query:
            m["economy_token_cap"] = {"from": base, "to": eco.max_tokens_per_query}
            context_budget = eco.max_tokens_per_query
    return plan, max_results, context_budget, m
