"""Optimized graphify_jev pipeline — the cascade (§16, §39, §40).

    ALL CANDIDATES (graph + BM25, ~50)
            │  scope filter                      free
            │  exact dedup + per-note cap        free
            ▼
    deterministic hybrid ranking                 free
            │  near-duplicate clustering (§10)   free
            │  zero-evidence flagging (§21)      free, shadow
            ▼
    adaptive top-K selection (§8)                free
            │  layered cache resolution (§11)    free after the first judgement
            ▼
    JEV relevance, in escalating waves (§8/§9)   PAID
            │  progressive expansion (§14)       PAID, ambiguous minority only
            │  gated injection (§15)             PAID, suspicious minority only
            ▼
    verdict propagation to duplicates (§10)      free
            ▼
    survivors -> full note text -> context budget

Every stage above the PAID line is deterministic, local and costs zero external tokens. That is the
whole thesis of this file: the judge should only ever see candidates that a free stage could not
resolve. The feature flags in config/optimization.py allow any subset to be enabled so each stage's
contribution can be measured separately and cumulatively (§30).

This function NEVER replaces `run_graphify_jev`. Both live side by side so the frozen baseline stays
runnable for comparison (§27, §38).
"""
from __future__ import annotations

import time

from app.gateway.token_budget import estimate_tokens
from app.retrieval.pipelines import _graphify_candidates, full_note_text
from app.schemas.models import Candidate
from app.services import adaptive as ad
from app.services.injection_screen import should_ask_injection
from app.services.jev import KEEP, QUARANTINE, UNSELECTED, route
from app.services.jev_cache import CacheIdentity, LayeredCache
from app.services.near_dup import cluster_near_duplicates, propagate
from app.services.prefilter import prefilter, rank
from app.services.query_fp import classify
from app.services.snippet import SNIPPET_POLICY_VERSION, extract


def _identity(gw, opt) -> CacheIdentity:
    j = gw.jev_cfg
    return CacheIdentity(
        model=j.model, prompt_version=j.prompt_version, jev_mode=j.mode,
        relevance_threshold=j.relevance_threshold, review_threshold=j.review_threshold,
        snippet_policy_version=(f"{SNIPPET_POLICY_VERSION}:{opt.snippet_tokens}"
                                if opt.smart_snippet else "raw"),
        namespace=getattr(gw, "cache_namespace", "") or "",
    )


def _apply_smart_snippets(gw, query: str, cands: list[Candidate], opt, cache: LayeredCache | None,
                          budget: int) -> dict:
    """Re-cut every candidate's snippet around the query-relevant region (§13).

    Runs on the FULL note text, not on the already-truncated snippet: re-cutting a prefix cut can
    only lose information, and the whole point is to reach a region the prefix never contained.

    Uses `snippet.fit_or_keep`, which guarantees the result is never larger than what the candidate
    already cost — see that function for the measured regression that made the guarantee necessary.
    """
    from app.services.dedup import content_hash
    from app.services.snippet import fit_or_keep

    replaced = 0
    kinds: dict[str, int] = {}
    before = after = 0
    qkey = list(classify(query).terms)
    for c in cands:
        original = c.snippet
        original_cost = c.token_estimate or estimate_tokens(original)
        before += original_cost
        try:
            text = gw.vault.read(c.source_file)
        except (OSError, PermissionError):
            after += original_cost
            continue
        cached = None
        if cache is not None and opt.cache_snippets:
            cached = cache.get_snippet(content_hash(text), SNIPPET_POLICY_VERSION, budget, qkey)
        if cached is not None:
            snippet, kind = cached, "cached"
        else:
            snippet, kind = fit_or_keep(text, original, query, budget, heading=c.section or "",
                                        min_saving=opt.snippet_min_saving)
            if cache is not None and opt.cache_snippets:
                cache.put_snippet(content_hash(text), SNIPPET_POLICY_VERSION, budget, qkey, snippet)
        new_cost = estimate_tokens(snippet)
        # Defence in depth: fit_or_keep already refuses to grow a snippet, but a cached entry was
        # written under a possibly different original, so the guard is re-applied here. `<=`, not
        # `<`: a same-price SECTION RELOCATION (snip-v2, kind == "relocated") costs no more than
        # `original` by construction but is not strictly cheaper, so it must still pass this gate.
        if snippet and snippet != original and new_cost <= original_cost:
            c.snippet = snippet
            c.content_hash = content_hash(snippet)
            c.token_estimate = new_cost
            c.meta = {**(c.meta or {}), "snippet_strategy": kind}
            replaced += 1
            kinds[kind] = kinds.get(kind, 0) + 1
            after += new_cost
        else:
            kinds["kept"] = kinds.get("kept", 0) + 1
            after += original_cost
    return {"snippet_replaced": replaced, "snippet_strategies": kinds,
            "snippet_tokens_before": before, "snippet_tokens_after": after,
            "snippet_tokens_saved": before - after, "snippet_budget": budget}


def safety_net_eligible(pool: list[Candidate]) -> list[Candidate]:
    """Candidates the safety net (§25) is allowed to deliver when the judge kept nothing.

    Two exclusions, for two different reasons:

    QUARANTINE — the judge actively flagged it as prompt injection. The net exists to avoid an
    empty answer, never to override a security verdict.

    UNSELECTED — we DELIBERATELY refused to pay for it (early stop / K ceiling). Delivering it
    would re-open the leak `jev.survives()` closes: the optimizer banks a judge-token saving and
    pays for it with consumer-context tokens, on a candidate nobody ever looked at. The net is for
    "the judge answered and rejected everything", not for "we never asked". This is reachable in
    practice when early stopping confirms a KEEP that the later gated injection pass then
    quarantines, which empties the survivor list while UNSELECTED candidates sit in the pool.
    """
    return [c for c in pool if c.decision not in (QUARANTINE, UNSELECTED)]


def select_pool(gw, query: str, max_results: int, opt=None):
    """Every FREE stage of the cascade: candidates -> smart snippets -> ranking -> dedup ->
    zero-evidence shadow -> adaptive-K / pre-filter. Stops right before the judge is called.

    Factored out of `run_graphify_jev_optimized` so a diagnostic (e.g.
    scripts/check_jev_snippet.py) can inspect exactly what the judge would receive — same
    candidate generation, same `extract()` budget, same pool selection — without spending a
    judge token. `opt.enabled=False` is the caller's job to check; this assumes the cascade runs.
    """
    from config.optimization import OptimizationConfig
    from types import SimpleNamespace

    opt = opt or getattr(gw, "opt_cfg", None) or OptimizationConfig()
    # Rejects flag combinations that were measured to be net losses (see config/optimization.py).
    opt.validate()

    rc = gw.retrieval_cfg
    jcfg = gw.jev_cfg
    uniq, metrics = _graphify_candidates(gw, query)
    t_free0 = time.perf_counter()

    # ---- query profiling (§18) -------------------------------------------------------------
    profile = classify(query)
    if opt.query_profiling:
        metrics.update(profile.to_dict())

    # ---- layered cache (§11) ---------------------------------------------------------------
    cache = None
    if opt.layered_cache:
        cache = LayeredCache(gw.db.cache_get, gw.db.cache_put, _identity(gw, opt),
                             promote_l3=opt.cache_promote_l3, enable_l2=opt.cache_l2,
                             enable_l3_shadow=opt.cache_l3_shadow)

    # ---- smart snippets (§13), BEFORE ranking so the lexical signal sees the real region ----
    if opt.smart_snippet:
        metrics.update(_apply_smart_snippets(
            gw, query, uniq, opt, cache,
            opt.progressive_first_tokens if opt.progressive_context else opt.snippet_tokens))

    # ---- deterministic ranking (§17) -------------------------------------------------------
    ordered = rank(query, uniq, rc.prefilter_lexical_weight)
    conf = ad.rank_confidence(query, ordered, rc.prefilter_lexical_weight)
    metrics.update(conf.to_dict())

    # ---- near-duplicate clustering (§10) ---------------------------------------------------
    clusters = []
    if opt.near_dedup:
        clusters, dm = cluster_near_duplicates(ordered, threshold=opt.near_dedup_threshold,
                                               hamming_max=opt.near_dedup_hamming)
        metrics.update(dm)
        ordered = [cl.rep for cl in clusters]

    # ---- zero-evidence shadow (§21) --------------------------------------------------------
    ze = ad.ZeroEvidence()
    if opt.zero_evidence_shadow or opt.zero_evidence_drop:
        ze.flagged = ad.zero_evidence(query, ordered)
        if opt.zero_evidence_drop:
            flagged_ids = {c.candidate_id for c in ze.flagged}
            for c in ze.flagged:
                c.decision = "DROP_DETERMINISTIC"
            ordered = [c for c in ordered if c.candidate_id not in flagged_ids]

    # ---- adaptive top-K (§8) ---------------------------------------------------------------
    if opt.adaptive_k:
        plan = ad.plan_k(profile, conf, max_total=min(opt.adaptive_k_max, len(ordered) or 1))
        waves = plan.waves()
        pool = ordered[:waves[-1]]
        withheld = ordered[waves[-1]:]
        metrics.update({"adaptive_k_start": plan.start, "adaptive_k_waves": waves,
                        "adaptive_k_reason": plan.reason, "prefilter_top_k": waves[-1],
                        "prefilter_in": len(ordered), "prefilter_sent": len(pool),
                        "prefilter_withheld": len(withheld), "prefilter_enabled": True})
    else:
        pool, withheld, pf = prefilter(query, ordered, rc.prefilter_top_k, rc.prefilter_lexical_weight)
        waves = None
        metrics.update(pf)
    metrics["free_stage_latency_ms"] = round((time.perf_counter() - t_free0) * 1000, 1)

    return SimpleNamespace(pool=pool, withheld=withheld, waves=waves, metrics=metrics,
                           cache=cache, profile=profile, conf=conf, rc=rc, jcfg=jcfg,
                           clusters=clusters, ze=ze, opt=opt)


def run_graphify_jev_optimized(gw, query: str, max_results: int, jev=None, opt=None):
    """Cascade pipeline. `opt` is an OptimizationConfig; with `opt.enabled=False` this delegates to
    the frozen baseline so a benchmark can use one code path for both arms."""
    from config.optimization import OptimizationConfig
    from app.retrieval.pipelines import run_graphify_jev

    opt = opt or getattr(gw, "opt_cfg", None) or OptimizationConfig()
    if not opt.enabled:
        return run_graphify_jev(gw, query, max_results, jev=jev)

    fs = select_pool(gw, query, max_results, opt=opt)
    pool, withheld, waves, metrics = fs.pool, fs.withheld, fs.waves, fs.metrics
    cache, rc, jcfg, clusters, ze = fs.cache, fs.rc, fs.jcfg, fs.clusters, fs.ze

    # ---- PAID stage ------------------------------------------------------------------------
    jev = jev or gw.jev
    if cache is not None:
        jev.layered = cache
    t0 = time.perf_counter()

    stop_check = None
    if opt.early_stopping:
        def stop_check(judged, remaining):  # noqa: E306
            # `pool` is the full ranked prefix, so ranks are the deterministic ranks the calibration
            # was measured against.
            return ad.should_stop(judged, remaining, keep_threshold=jcfg.relevance_threshold,
                                  review_threshold=jcfg.review_threshold,
                                  min_strong=opt.early_stop_min_strong,
                                  max_accept_rank=opt.early_stop_max_accept_rank,
                                  max_results=max_results, order=pool)

    ask_inj = None
    if opt.strict_gating:
        def ask_inj(c):  # noqa: E306
            return should_ask_injection(c.snippet, c.relevance, jcfg.relevance_threshold,
                                        jcfg.review_threshold,
                                        gate_on_relevance=opt.strict_gate_on_relevance,
                                        screen_enabled=opt.strict_lexical_screen)

    expand = None
    if opt.progressive_context:
        def expand(c, budget):  # noqa: E306
            """Grow ONE candidate's snippet, and only if growing actually adds information.

            Symmetric to the ceiling rule in `snippet.fit_or_keep`: expansion is the one place the
            payload is allowed to get bigger, so it must refuse to spend when there is nothing to
            gain. A candidate whose snippet is already the whole note cannot be expanded, and paying
            a second judgement for identical text is pure waste.
            """
            from app.services.dedup import content_hash
            try:
                text = gw.vault.read(c.source_file)
            except (OSError, PermissionError):
                return
            res = extract(text, query, budget, heading=c.section or "")
            if not res.text or res.text == c.snippet:
                return
            if res.tokens <= (c.token_estimate or 0):
                return
            c.snippet = res.text
            c.content_hash = content_hash(res.text)
            c.token_estimate = res.tokens
            c.meta = {**(c.meta or {}), "expanded_to": budget}

    survivors, jm = jev.evaluate_adaptive(
        query, pool, waves=waves, stop_check=stop_check, ask_injection=ask_inj,
        expand=expand, expand_band=opt.progressive_band if opt.progressive_context else 0.0,
        expand_tokens=opt.progressive_second_tokens if opt.progressive_context else 0)
    t1 = time.perf_counter()

    # ---- propagate verdicts to duplicate cluster members (§10) -----------------------------
    if opt.near_dedup and clusters:
        judged_ids = {c.candidate_id for c in pool}
        live = [cl for cl in clusters if cl.rep.candidate_id in judged_ids]
        jm.propagated_decisions = propagate(live)
        extra = [m_ for cl in live for m_ in cl.members
                 if m_.decision == KEEP or (m_.decision == "REVIEW" and jcfg.review_action == "keep")]
        # A propagated survivor must not displace a judged one: it is appended, never merged into
        # the ranking, and de-duplicated by source_file so the context never shows the same note twice.
        seen_files = {c.source_file for c in survivors}
        for c in extra:
            if c.source_file not in seen_files:
                survivors.append(c)
                seen_files.add(c.source_file)

    # ---- zero-evidence shadow scoring (§21/§33) --------------------------------------------
    if (opt.zero_evidence_shadow and not opt.zero_evidence_drop) and ze.flagged:
        judged_flagged = [c for c in ze.flagged if c.relevance is not None]
        for c in judged_flagged:
            band = route(c.relevance, None, jcfg)
            ze.scores.append(c.relevance)
            if band == "DROP":
                ze.agreements += 1
            else:
                ze.disagreements += 1
        metrics.update(ze.to_dict())
        metrics["zero_evidence_measured"] = len(judged_flagged)

    survivors = sorted(survivors, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]

    # ---- SAFETY NET (§25) — identical rule as the baseline ---------------------------------
    fallback_used = 0
    if not survivors and pool:
        safe = safety_net_eligible(pool)
        fb = sorted(safe, key=lambda c: -c.score)[:min(rc.jev_min_survivors, max_results)]
        for c in fb:
            c.decision = f"{c.decision}_FALLBACK" if c.decision else "FALLBACK"
        survivors, fallback_used = fb, len(fb)

    full = {c.candidate_id: full_note_text(gw, c) for c in survivors}
    t2 = time.perf_counter()
    jd = jm.to_dict()
    metrics.update({
        "filter_latency_ms": round(metrics.pop("dedup_latency_ms", 0.0) + (t1 - t0) * 1000, 1),
        "jev_latency_ms": jd["latency_ms"],
        "full_note_latency_ms": round((t2 - t1) * 1000, 1),
        "documents_sent_to_jev": len(pool),
        "documents_kept": jd["candidates_kept"],
        "documents_review": jd["candidates_review"],
        "documents_dropped": jd["candidates_dropped"],
        "documents_quarantined": jd["candidates_quarantined"],
        "documents_unjudged": jd["candidates_unjudged"],
        "documents_unselected": jd["candidates_unselected"],
        "jev_fallback_used": fallback_used,
        "survivor_tokens_snippets": sum(c.token_estimate or 0 for c in survivors),
        "jev_input_tokens": jd["input_tokens"],
        "jev_output_tokens": jd["output_tokens"],
        "jev_cache_hits": jd["cache_hits"],
        "jev_cache_enabled": jd["cache_enabled"],
        "jev_relevance_questions": jd["relevance_questions"],
        "jev_injection_questions": jd["injection_questions"],
        "jev_injection_skipped": jd["injection_skipped"],
        "jev_waves": jd["waves"],
        "jev_wave_sizes": jd["wave_sizes"],
        "jev_propagated": jd["propagated_decisions"],
        "jev_progressive_expansions": jd["progressive_expansions"],
        "cache_layers": jd["cache_layers"],
        "opt_flags": opt.active_flags(),
        "opt_version": opt.version,
        "jev": jd,
        "_all_candidates": pool + withheld + [m_ for cl in clusters for m_ in cl.members],
    })
    return survivors, full, metrics
