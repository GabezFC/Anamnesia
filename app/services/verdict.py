"""Veredito -- pipeline routing decision for MemoryGateway.search(pipeline="auto").

This is NOT a second "auto" mechanism (proposta 2026-09-28 §1.2/§5.6): it wraps the SAME
`MG_ROUTE_SIMPLE/MEDIUM/COMPLEX/AMBIGUOUS` routes already on `OptimizerConfig`
(config/optimizer.py, applied in app/gateway/optimizer.py). docs/SCOPE_BENCHMARK.md (2026-09-29,
real vault + 520-note synthetic corpus, every scope bucket measured) found no case where switching
away from `baseline` was justified, so `decide()` below never overrides `cfg.route_for()` -- it
only records an audited "why", including a cheap deterministic size estimate, alongside the
decision the router already makes. When a future benchmark finds a threshold worth acting on, only
`cfg.route_for()` / the `MG_ROUTE_*` env vars need to change -- this function's job is bookkeeping,
not a second routing table.
"""
from __future__ import annotations

from config.optimizer import OptimizerConfig


def decide(query: str, complexity: str, size_estimate: int | None,
           cfg: OptimizerConfig) -> tuple[str, str]:
    """Pure function: (pipeline, reason) for one 'auto' request. No I/O, no model call.

    `size_estimate` is a candidate count from a cheap lexical pre-filter (see
    BaselineIndex.count(), wired in app/gateway/optimizer.py) or None when it could not be
    computed. The chosen pipeline is IDENTICAL either way -- only the recorded reason changes --
    so a failed size probe can never change which pipeline answers the query.
    """
    pipeline = cfg.route_for(complexity)
    if size_estimate is None:
        return pipeline, f"verdict:{complexity}:size_unknown"
    if size_estimate <= cfg.verdict_small_max:
        bucket = "small"
    elif size_estimate >= cfg.verdict_large_min:
        bucket = "large"
    else:
        bucket = "medium"
    return pipeline, f"verdict:{complexity}:{bucket}:{size_estimate}"
