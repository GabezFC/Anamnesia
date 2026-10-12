"""Pipeline registry (ANA-107 / ANA-132). Imports nothing from the other pipeline modules.

`PIPELINE_FUNCS` maps a pipeline name to `fn(gw, query, max_results[, jev]) -> (cands, full, metrics)`.
Modules register themselves here; callers (and `pipelines_opt`, which needs the frozen
`graphify_jev` for its `enabled=False` path) look pipelines up by name instead of importing each
other -- that is what removed the pipelines <-> pipelines_opt cycle.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable

from app.core.ports import Judge, Retriever

PipelineFn = Callable[..., tuple[list, dict, dict[str, Any]]]

PIPELINE_FUNCS: dict[str, PipelineFn] = {}


def register_pipeline(name: str, fn: PipelineFn, *, replace: bool = False) -> PipelineFn:
    if name in PIPELINE_FUNCS and not replace:
        raise ValueError(f"pipeline already registered: {name}")
    PIPELINE_FUNCS[name] = fn
    return fn


def unregister_pipeline(name: str) -> None:
    PIPELINE_FUNCS.pop(name, None)


def get_pipeline(name: str) -> PipelineFn:
    if name not in PIPELINE_FUNCS:
        # importlib (string) on purpose: loads the standard registrations without a static edge.
        importlib.import_module("app.retrieval.pipelines")
    try:
        return PIPELINE_FUNCS[name]
    except KeyError:
        raise KeyError(f"pipeline not registered: {name} (known: {sorted(PIPELINE_FUNCS)})") from None


def compose_pipeline(retriever: Retriever, judge: Judge | None = None) -> PipelineFn:
    """ANA-132: build a pipeline from a `Retriever` and an optional `Judge`.

    Candidates are fetched with `gw.active_scope`, judged if a judge exists, ordered by
    (relevance, score) and cut to `max_results`. Returns (cands, full_texts, metrics).
    """

    def _run(gw, query: str, max_results: int, jev=None):
        scope = getattr(gw, "active_scope", None)
        cands = list(retriever.search(query, scope, max_results))
        metrics: dict[str, Any] = {"documents_found": len(cands)}
        j = jev or judge
        if j is not None and cands:
            cands, jm = j.evaluate(query, cands)
            metrics["judge"] = jm
        cands = sorted(cands, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]
        return cands, {}, metrics

    return _run
