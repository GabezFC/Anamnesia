"""Pipeline implementations. Each returns (final_candidates, full_texts, metrics) to the gateway.

A: baseline      search -> preprocess -> dedup -> (budget in ModelContextBuilder)
B: graphify      graphify -> preprocess -> dedup -> (budget)
C: graphify_jev  graphify -> preprocess -> dedup -> JEV batch -> code routing -> survivors
                 -> full-note retrieval (survivors only) -> (budget)
"""
from __future__ import annotations

import time
from typing import Any

from app.core.tokens import estimate_tokens
from app.retrieval.registry import PIPELINE_FUNCS, register_pipeline
from app.retrieval.experiments import dedup_limit, lexical_search, post_dedup
from app.retrieval.common import (_apply_scope, _graphify_candidates, _tokens,  # noqa: F401
                                  full_note_text)
from app.schemas.models import PIPELINES, Candidate
from app.services.dedup import deduplicate, preprocess
from app.services.jev import QUARANTINE
from app.services.obsidian import split_sections
from app.services.prefilter import prefilter


def run_baseline(gw, query: str, max_results: int) -> tuple[list[Candidate], dict, dict[str, Any]]:
    rc = gw.retrieval_cfg
    t0 = time.perf_counter()
    raw = lexical_search(gw, query, rc.max_candidates)   # == gw.baseline.search(...) with every Onda 9 flag off
    t1 = time.perf_counter()
    raw, out_of_scope = _apply_scope(gw, raw)
    cands = preprocess(raw, rc.snippet_max_tokens)
    cand_tokens = _tokens(cands)
    uniq, removed = deduplicate(cands, dedup_limit(gw, query, rc.dedup_max_per_note))
    uniq = post_dedup(gw, query, uniq)
    t2 = time.perf_counter()
    final = uniq[:max_results]
    return final, {}, {
        "retrieval_latency_ms": round((t1 - t0) * 1000, 1),
        "filter_latency_ms": round((t2 - t1) * 1000, 1),
        "documents_found": len(raw),
        "documents_out_of_scope": out_of_scope,
        "documents_deduplicated": removed,
        "candidate_tokens_before_filter": cand_tokens,
        "baseline_sections_indexed": gw.baseline.sections_indexed,
    }


def run_graphify(gw, query: str, max_results: int):
    uniq, metrics = _graphify_candidates(gw, query)
    metrics["filter_latency_ms"] = metrics.pop("dedup_latency_ms")
    return uniq[:max_results], {}, metrics


def run_graphify_jev(gw, query: str, max_results: int, jev=None):
    # allow_ppr=False: graphify_jev is frozen (§5.5) — PPR_ENABLED must never change its output.
    uniq, metrics = _graphify_candidates(gw, query, allow_ppr=False)
    jev = jev or gw.jev
    rc = gw.retrieval_cfg
    # Deterministic top-K cut BEFORE the paid judge (zero tokens). See app/services/prefilter.py.
    judged_in, withheld, pf = prefilter(query, uniq, rc.prefilter_top_k, rc.prefilter_lexical_weight)
    metrics.update(pf)
    t0 = time.perf_counter()
    survivors, jm = jev.evaluate(query, judged_in)
    t1 = time.perf_counter()
    survivors = sorted(survivors, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]

    # SAFETY NET (§25). Measured 2026-09-27: the judge scores correct notes 0.07-0.40 for some
    # questions, so q05/q07/q10 survived with ZERO candidates and the user got an EMPTY context
    # while still paying the judge. Returning nothing is strictly worse than returning the best
    # retrieval candidates unjudged, so when the judge eliminates everything we fall back to the
    # top pre-filter candidates and flag it. This never overrides a QUARANTINE (injection) call.
    fallback_used = 0
    if not survivors and judged_in:
        safe = [c for c in judged_in if c.decision != QUARANTINE]
        fallback = sorted(safe, key=lambda c: -c.score)[:min(rc.jev_min_survivors, max_results)]
        for c in fallback:
            c.decision = f"{c.decision}_FALLBACK" if c.decision else "FALLBACK"
        survivors = fallback
        fallback_used = len(fallback)

    full = {c.candidate_id: full_note_text(gw, c) for c in survivors}
    t2 = time.perf_counter()
    jd = jm.to_dict()
    metrics.update({
        "filter_latency_ms": round(metrics.pop("dedup_latency_ms") + (t1 - t0) * 1000, 1),
        "jev_latency_ms": jd["latency_ms"],
        "full_note_latency_ms": round((t2 - t1) * 1000, 1),
        "documents_sent_to_jev": len(judged_in),
        "documents_kept": jd["candidates_kept"],
        "documents_review": jd["candidates_review"],
        "documents_dropped": jd["candidates_dropped"],
        "documents_quarantined": jd["candidates_quarantined"],
        "documents_unjudged": jd["candidates_unjudged"],
        "jev_fallback_used": fallback_used,
        "survivor_tokens_snippets": _tokens(survivors),
        "jev_input_tokens": jd["input_tokens"],
        "jev_output_tokens": jd["output_tokens"],
        "jev_cache_hits": jd["cache_hits"],
        "jev_cache_enabled": jd["cache_enabled"],
        "jev": jd,
        # every judged candidate plus the ones withheld by the pre-filter, so a survivor the
        # pre-filter dropped can still be marked as a false negative later (§25).
        "_all_candidates": judged_in + withheld,
    })
    return survivors, full, metrics


# ANA-107/132: the dict lives in registry.py (no imports of pipeline modules). Importing
# pipelines_opt is one-directional now (it reaches the frozen pipeline through the registry).
register_pipeline("baseline", run_baseline)
register_pipeline("graphify", run_graphify)
register_pipeline("graphify_jev", run_graphify_jev)

from app.retrieval import pipelines_opt as _pipelines_opt  # noqa: E402  (registers graphify_jev_opt)

assert set(PIPELINE_FUNCS) == set(PIPELINES), (
    "PIPELINE_FUNCS must register exactly the pipelines in app.schemas.models.PIPELINES")
