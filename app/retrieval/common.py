"""Helpers shared by the retrieval pipelines (ANA-107).

Extracted from `pipelines.py` so `pipelines_opt.py` no longer needs to import `pipelines` at module
level (that was the pipelines <-> pipelines_opt import cycle).
"""
from __future__ import annotations

import time

from app.core.tokens import estimate_tokens
from app.retrieval.experiments import dedup_limit, post_dedup
from app.retrieval.graphify_hybrid import hybrid_search
from app.schemas.models import Candidate
from app.services.dedup import deduplicate, preprocess
from app.services.obsidian import split_sections


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


def _graphify_candidates(gw, query: str, allow_ppr: bool = True):
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
                                   graph_expand=rc.graphify_graph_expand,
                                   allow_ppr=allow_ppr)
    else:
        raw, ginfo = gw.graphify.search(query, limit=rc.max_candidates)
        ginfo = {**ginfo, "graphify_mode": "cli"}
    t1 = time.perf_counter()
    raw, out_of_scope = _apply_scope(gw, raw)
    cands = preprocess(raw, rc.snippet_max_tokens)
    cand_tokens = _tokens(cands)
    uniq, removed = deduplicate(cands, dedup_limit(gw, query, rc.dedup_max_per_note, frozen=not allow_ppr))
    uniq = post_dedup(gw, query, uniq, frozen=not allow_ppr)
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
