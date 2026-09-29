"""Pipeline implementations. Each returns (final_candidates, full_texts, metrics) to the gateway.

A: baseline      search -> preprocess -> dedup -> (budget in ModelContextBuilder)
B: graphify      graphify -> preprocess -> dedup -> (budget)
C: graphify_jev  graphify -> preprocess -> dedup -> JEV batch -> code routing -> survivors
                 -> full-note retrieval (survivors only) -> (budget)
"""
from __future__ import annotations

import time
from typing import Any

from app.gateway.token_budget import estimate_tokens
from app.retrieval.graphify_hybrid import hybrid_search
from app.schemas.models import PIPELINES, Candidate
from app.services.dedup import deduplicate, preprocess
from app.services.jev import QUARANTINE
from app.services.obsidian import split_sections
from app.services.prefilter import prefilter


def _tokens(cands: list[Candidate]) -> int:
    return sum(c.token_estimate or estimate_tokens(c.snippet) for c in cands)


def _apply_scope(gw, cands: list[Candidate]) -> tuple[list[Candidate], int]:
    """Drop out-of-scope candidates as EARLY as possible (§14).

    Scoping before the judge (not only before context building) is what makes multi-project
    isolation cheap: an out-of-scope note that is filtered here never costs judge tokens.
    """
    scope = getattr(gw, "active_scope", None)
    if scope is None or scope.is_global:
        return cands, 0
    kept = [c for c in cands if scope.matches(c.source_file)]
    return kept, len(cands) - len(kept)


def run_baseline(gw, query: str, max_results: int) -> tuple[list[Candidate], dict, dict[str, Any]]:
    rc = gw.retrieval_cfg
    t0 = time.perf_counter()
    raw = gw.baseline.search(query, limit=rc.max_candidates)
    t1 = time.perf_counter()
    raw, out_of_scope = _apply_scope(gw, raw)
    cands = preprocess(raw, rc.snippet_max_tokens)
    cand_tokens = _tokens(cands)
    uniq, removed = deduplicate(cands, rc.dedup_max_per_note)
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


def _graphify_candidates(gw, query: str):
    rc = gw.retrieval_cfg
    t0 = time.perf_counter()
    # Hybrid needs a real graph.json to expand structurally. When it is absent (fresh checkout,
    # graph not built yet, or an injected test double), fall back to the service's own search so
    # behaviour degrades to the previous pipeline instead of silently losing the graph stage.
    index = getattr(gw, "graph_index", None)
    if index is not None:
        index.load()
    use_hybrid = getattr(rc, "graphify_hybrid", True) and index is not None and index.loaded
    if use_hybrid:
        # BM25 body text for content + graph edges for structure. Recall 10/10 vs 8/10 for the
        # CLI traversal (measured 2026-09-27). See app/retrieval/graphify_hybrid.py.
        raw, ginfo = hybrid_search(gw, query, rc.max_candidates,
                                   text_seeds=rc.graphify_text_seeds,
                                   graph_expand=rc.graphify_graph_expand)
    else:
        raw, ginfo = gw.graphify.search(query, limit=rc.max_candidates)
        ginfo = {**ginfo, "graphify_mode": "cli"}
    t1 = time.perf_counter()
    raw, out_of_scope = _apply_scope(gw, raw)
    cands = preprocess(raw, rc.snippet_max_tokens)
    cand_tokens = _tokens(cands)
    uniq, removed = deduplicate(cands, rc.dedup_max_per_note)
    t2 = time.perf_counter()
    scores = [c.score for c in raw]
    metrics = {
        "retrieval_latency_ms": round((t1 - t0) * 1000, 1),
        "dedup_latency_ms": round((t2 - t1) * 1000, 1),
        "documents_found": len(raw),
        "documents_out_of_scope": out_of_scope,
        "documents_deduplicated": removed,
        "candidate_tokens_before_filter": cand_tokens,
        "average_graphify_score": round(sum(scores) / len(scores), 4) if scores else None,
        **ginfo,
    }
    return uniq, metrics


def run_graphify(gw, query: str, max_results: int):
    uniq, metrics = _graphify_candidates(gw, query)
    metrics["filter_latency_ms"] = metrics.pop("dedup_latency_ms")
    return uniq[:max_results], {}, metrics


def full_note_text(gw, c: Candidate) -> str:
    """Full-note retrieval for a survivor (§28). Only survivors are expanded.

    The matched section comes first (it is what JEV judged relevant), followed by the rest of the note
    in document order, frontmatter removed. ModelContextBuilder caps it at PER_SOURCE_MAX_TOKENS.
    Graphify frequently points at a note's H1 node, whose own section is only the title, so returning
    the whole note is required to deliver actual content.
    """
    text = gw.vault.read(c.source_file)
    secs = split_sections(text)
    target = next((s for s in secs if s.heading_path == c.section), None)
    ordered = ([target] if target else []) + [s for s in secs if s is not target]
    return "\n\n".join(s.text for s in ordered if s.text.strip()) or c.snippet


def run_graphify_jev(gw, query: str, max_results: int, jev=None):
    uniq, metrics = _graphify_candidates(gw, query)
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


PIPELINE_FUNCS = {"baseline": run_baseline, "graphify": run_graphify, "graphify_jev": run_graphify_jev}


def _optimized(gw, query: str, max_results: int, jev=None):
    """PIPELINE D — the cascade. Registered lazily to avoid a circular import at module load."""
    from app.retrieval.pipelines_opt import run_graphify_jev_optimized
    return run_graphify_jev_optimized(gw, query, max_results, jev=jev)


PIPELINE_FUNCS["graphify_jev_opt"] = _optimized

assert set(PIPELINE_FUNCS) == set(PIPELINES), (
    "PIPELINE_FUNCS must register exactly the pipelines in app.schemas.models.PIPELINES")
