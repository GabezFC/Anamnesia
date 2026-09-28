"""Stacked optimization benchmark (§26–§31, §33). Measures, never assumes.

WHAT THIS PRODUCES
------------------
For each ARM (a named OptimizationConfig), for every question in the dataset:
    tokens_input / tokens_output / total_tokens / final_context_tokens
    amplification_factor = total_tokens_spent / context_tokens
    jev_calls (requests) / relevance_questions / injection_questions / injection_skipped
    candidates_found / candidates_sent_to_jev / candidate_reduction
    cache hits per layer / negative hits / L3 shadow false-positive rate
    KEEP / REVIEW / DROP / QUARANTINE / UNJUDGED
    recall (expected_sources found in the delivered context) / precision
    latency / estimated_cost
    routing agreement vs the BASELINE arm, per candidate, with every divergence recorded

Two properties make the numbers trustworthy:

1. THE BASELINE ARM IS ALWAYS RUN FIRST AND NEVER MODIFIED (§27). Every other arm is compared
   against it on the SAME questions in the SAME order.
2. CACHE ARMS ARE MEASURED HONESTLY. A cache's whole value is amortization, so a cache arm is run
   over TWO passes: pass 1 is cold (it pays full price and populates), pass 2 replays the questions
   INCLUDING their paraphrases. Reporting only the warm pass would be dishonest; reporting only the
   cold pass would claim a cache is useless. Both are reported, plus the combined figure.

COST CONTROL
------------
Every arm costs real money. `--limit` caps questions, `--arms` selects arms, and `estimate` prints
the projected token spend before anything is sent. The runner also records the exact
question/arm/run_id mapping in SQLite so a partial run is resumable rather than repeatable.

CACHE ISOLATION (this bit is not optional)
------------------------------------------
Measured failure on the first run: the BASELINE arm reported `judge=0` for the first three questions
and won the comparison by a factor of two. It had not become efficient — it was reading judgements
cached by an EARLIER smoke run, while `full_stack` (a different identity vector, hence different keys)
paid full price. Comparing a warm arm against a cold one measures run order, not optimization.

Two different questions need two different isolation policies, and conflating them produced a second
measured failure (arm `05_early_stopping` reported 0 judge tokens because the arm before it had
already populated the cache):

  --isolation arm   (DEFAULT) every arm gets its own namespace. Each arm pays full price, so its
                    judge-token total is ATTRIBUTABLE to its own mechanisms. This is what the
                    per-arm stack table needs.
  --isolation run   all arms share one namespace. Later arms read earlier arms' judgements, which
                    measures the cache and nothing else. Only meaningful with --two-pass.
  --isolation none  the production namespace; this run may read any earlier run's work. Never valid
                    for a comparison, offered only for debugging a live cache.

`--two-pass` is the correct way to measure amortization: within ONE arm, pass 1 is cold and pass 2
replays the same questions plus their paraphrases, so the warm figure is a property of the arm rather
than of the order the arms happened to run in.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(PROJECT_ROOT))

from config.optimization import OptimizationConfig  # noqa: E402
from app.services.pricing import cost_usd  # noqa: E402

# ---------------------------------------------------------------------------------------------
# ARMS — the cumulative stack (§30). Each arm adds exactly ONE mechanism to the previous one, so a
# difference between consecutive rows is attributable to that mechanism and nothing else.
# ---------------------------------------------------------------------------------------------
def build_arms() -> dict[str, OptimizationConfig]:
    """The cumulative stack (§30). Each arm adds exactly ONE mechanism to the previous one.

    EXCEPTION, and it is a measured one: adaptive_k and early_stopping are added TOGETHER.
    They were originally separate arms, and that produced a misleading table — adaptive_k alone cost
    +20.0% because waves without a stop rule escalate on every query, paying an extra 340-token
    request to ask questions one request could have carried. The two are a single mechanism
    ("spend less when the ranker was already decisive"), and `OptimizationConfig.validate()` now
    rejects the combination adaptive_k without early_stopping. The isolated numbers are preserved in
    the vault (arquitetura/otimizacoes-rejeitadas-por-medicao.md) rather than re-measured every run.
    """
    base = OptimizationConfig.baseline()
    a1 = base.with_(enabled=True, query_profiling=True, record_shadow_metrics=True,
                    zero_evidence_shadow=True)
    a2 = a1.with_(near_dedup=True)
    a3 = a2.with_(layered_cache=True, cache_l2=True, cache_l3_shadow=True)
    a4 = a3.with_(adaptive_k=True, early_stopping=True)
    a5 = a4.with_(smart_snippet=True, cache_snippets=True)
    a6 = a5.with_(progressive_context=True)
    a7 = a6.with_(strict_gating=True)
    return {
        "baseline": base,
        "01_profiling_shadow": a1,
        "02_near_dedup": a2,
        "03_layered_cache": a3,
        "04_adaptive_k_early_stop": a4,
        "05_smart_snippet": a5,
        "06_progressive": a6,
        "07_strict_gating": a7,
        "full_stack": a7,
    }


# Arms whose value only appears on a second pass over the same/paraphrased queries.
CACHE_ARMS = {"03_layered_cache", "04_adaptive_k_early_stop", "05_smart_snippet", "06_progressive",
              "07_strict_gating", "full_stack"}


@dataclass
class QuestionResult:
    qid: str
    arm: str
    pass_no: int
    run_id: str | None
    context_tokens: int
    jev_input: int | None
    jev_output: int | None
    total_tokens: int
    amplification: float | None
    jev_calls: int
    relevance_questions: int
    injection_questions: int
    injection_skipped: int
    candidates_found: int
    candidates_sent: int
    cache_hits: int
    keep: int
    review: int
    drop: int
    quarantine: int
    unjudged: int
    # Candidates the optimizer DELIBERATELY refused to pay for (early stop / K ceiling). Reported
    # separately from `unjudged` because they are opposite states, and because their count is what
    # proves the context leak stays closed: unselected candidates must never reach the consumer, so
    # `candidates_sent` MUST equal keep+review+drop+quarantine+unjudged+unselected. Without this
    # field the arithmetic silently did not close and the leak was invisible in the report.
    unselected: int
    recall: float | None
    precision: float | None
    latency_ms: float
    cost_usd: float
    fallback: int
    empty_context: bool
    decisions: dict[str, str] = field(default_factory=dict)      # candidate_id -> decision
    relevances: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d.pop("metrics", None)
        return d


def _recall_precision(question: dict, result) -> tuple[float | None, float | None]:
    """Recall/precision of the DELIVERED CONTEXT, not of the candidate pool.

    This is the only definition that matters for the mission: a note the judge kept but the context
    builder dropped for budget reasons was not delivered, and a token saving that pushes a relevant
    note out of the context is a recall loss no matter where it happened.
    """
    exp = question.get("expected_sources") or []
    got = {s.file for s in result.sources}
    if not exp:
        # Unanswerable question: recall is undefined; precision is 1.0 only if nothing was returned.
        return None, (1.0 if not got else 0.0)
    hits = sum(1 for e in exp if e in got)
    recall = hits / len(exp)
    precision = (hits / len(got)) if got else 0.0
    return round(recall, 4), round(precision, 4)


def run_arm(gw, arm: str, opt: OptimizationConfig, questions: list[dict], *,
            pass_no: int, max_results: int, session_id: str,
            progress: Callable[[str], None] | None = None) -> list[QuestionResult]:
    """Run one arm over the dataset once. The gateway's opt_cfg is swapped for the duration."""
    pipeline = "graphify_jev" if arm == "baseline" else "graphify_jev_opt"
    prev = gw.opt_cfg
    gw.opt_cfg = opt
    out: list[QuestionResult] = []
    try:
        for q in questions:
            t0 = time.perf_counter()
            r = gw.search(q["question"], pipeline, max_results,
                          run_meta={"session_id": session_id, "question_id": q.get("id"),
                                    "kind": "opt_benchmark",
                                    "mode": f"{arm}|pass{pass_no}"})
            m = r.metrics
            recall, precision = _recall_precision(q, r)
            jd = m.get("jev") or {}
            res = QuestionResult(
                qid=q.get("id", "?"), arm=arm, pass_no=pass_no, run_id=r.run_id,
                context_tokens=m.get("context_tokens") or 0,
                jev_input=m.get("jev_input_tokens"), jev_output=m.get("jev_output_tokens"),
                total_tokens=m.get("total_tokens_spent") or 0,
                amplification=m.get("token_amplification"),
                jev_calls=jd.get("request_count") or 0,
                relevance_questions=jd.get("relevance_questions") or 0,
                injection_questions=jd.get("injection_questions") or 0,
                injection_skipped=jd.get("injection_skipped") or 0,
                candidates_found=m.get("documents_found") or 0,
                candidates_sent=m.get("documents_sent_to_jev") or 0,
                cache_hits=jd.get("cache_hits") or 0,
                keep=m.get("documents_kept") or 0, review=m.get("documents_review") or 0,
                drop=m.get("documents_dropped") or 0,
                quarantine=m.get("documents_quarantined") or 0,
                unjudged=m.get("documents_unjudged") or 0,
                unselected=m.get("documents_unselected") or 0,
                recall=recall, precision=precision,
                latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                cost_usd=m.get("jev_cost") or 0.0,
                fallback=m.get("jev_fallback_used") or 0,
                empty_context=not bool((r.context or "").strip()),
                decisions={c.candidate_id: (c.decision or "?") for c in r.candidates},
                relevances={c.candidate_id: c.relevance for c in r.candidates
                            if c.relevance is not None},
                metrics=m,
            )
            out.append(res)
            if progress:
                progress(f"  {arm} pass{pass_no} {res.qid}: ctx={res.context_tokens} "
                         f"judge={res.jev_input} amp={res.amplification} recall={res.recall}")
    finally:
        gw.opt_cfg = prev
    return out


def _agg(values: list[float | None]) -> dict:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"mean": None, "median": None, "min": None, "max": None, "sum": None, "n": 0}
    return {"mean": round(statistics.fmean(vals), 4), "median": round(statistics.median(vals), 4),
            "min": round(min(vals), 4), "max": round(max(vals), 4),
            "sum": round(sum(vals), 4), "n": len(vals)}


def summarize(arm: str, results: list[QuestionResult], baseline: list[QuestionResult] | None) -> dict:
    """Arm-level aggregate plus the divergence analysis against the baseline (§33)."""
    by_q = {r.qid: r for r in results}
    total_judge = sum((r.jev_input or 0) + (r.jev_output or 0) for r in results)
    total_ctx = sum(r.context_tokens for r in results)
    out: dict[str, Any] = {
        "arm": arm,
        "questions": len(results),
        "judge_tokens_total": total_judge,
        "context_tokens_total": total_ctx,
        "total_tokens_total": sum(r.total_tokens for r in results),
        "amplification_overall": round(sum(r.total_tokens for r in results) / total_ctx, 3) if total_ctx else None,
        "judge_tokens": _agg([(r.jev_input or 0) + (r.jev_output or 0) for r in results]),
        "context_tokens": _agg([r.context_tokens for r in results]),
        "amplification": _agg([r.amplification for r in results]),
        "jev_calls_total": sum(r.jev_calls for r in results),
        "relevance_questions_total": sum(r.relevance_questions for r in results),
        "injection_questions_total": sum(r.injection_questions for r in results),
        "injection_skipped_total": sum(r.injection_skipped for r in results),
        "candidates_found_total": sum(r.candidates_found for r in results),
        "candidates_sent_total": sum(r.candidates_sent for r in results),
        "candidate_reduction": (round(sum(r.candidates_found for r in results) /
                                      sum(r.candidates_sent for r in results), 3)
                                if sum(r.candidates_sent for r in results) else None),
        "cache_hits_total": sum(r.cache_hits for r in results),
        "recall": _agg([r.recall for r in results]),
        "precision": _agg([r.precision for r in results]),
        "latency_ms": _agg([r.latency_ms for r in results]),
        "cost_usd_total": round(sum(r.cost_usd for r in results), 6),
        "empty_contexts": sum(1 for r in results if r.empty_context),
        "fallbacks": sum(r.fallback for r in results),
        "routing": {
            "KEEP": sum(r.keep for r in results), "REVIEW": sum(r.review for r in results),
            "DROP": sum(r.drop for r in results), "QUARANTINE": sum(r.quarantine for r in results),
            "UNJUDGED": sum(r.unjudged for r in results),
            "UNSELECTED": sum(r.unselected for r in results),
        },
    }
    # LEAK INVARIANT (§25). Every candidate sent to the paid stage must end in exactly one routing
    # state. If this does not close, some candidate is being counted twice or — the bug this whole
    # round fixed — an UNSELECTED candidate is being silently reclassified so it can survive into
    # the consumer's context. A benchmark that cannot prove this is not auditable.
    routed = sum(out["routing"].values())
    out["routing_accounts_for_all_candidates"] = (routed == out["candidates_sent_total"])
    out["routing_unaccounted"] = out["candidates_sent_total"] - routed
    dropped_share = out["routing"]["DROP"] + out["routing"]["QUARANTINE"]
    judged_total = sum(out["routing"].values())
    out["drop_share"] = round(dropped_share / judged_total, 4) if judged_total else None

    if baseline is None:
        return out

    base_q = {r.qid: r for r in baseline}
    # --- recall delta, the metric that can veto an arm (§34) -------------------------------
    pairs = [(base_q[q].recall, by_q[q].recall) for q in by_q
             if q in base_q and base_q[q].recall is not None and by_q[q].recall is not None]
    regressions = [q for q in by_q if q in base_q and base_q[q].recall is not None
                   and by_q[q].recall is not None and by_q[q].recall < base_q[q].recall]
    out["recall_vs_baseline"] = {
        "baseline_mean": round(statistics.fmean([b for b, _ in pairs]), 4) if pairs else None,
        "arm_mean": round(statistics.fmean([a for _, a in pairs]), 4) if pairs else None,
        "delta": round(statistics.fmean([a - b for b, a in pairs]), 4) if pairs else None,
        "questions_regressed": sorted(regressions),
        "questions_regressed_n": len(regressions),
    }
    # --- routing agreement, per candidate (§33) --------------------------------------------
    agree = disagree = 0
    divergences: list[dict] = []
    for qid, r in by_q.items():
        b = base_q.get(qid)
        if not b:
            continue
        for cid, bdec in b.decisions.items():
            adec = r.decisions.get(cid)
            if adec is None:
                continue          # the arm never judged it: counted as an avoided judgement, not a disagreement
            if adec == bdec:
                agree += 1
            else:
                disagree += 1
                divergences.append({"qid": qid, "candidate": cid, "baseline": bdec, "arm": adec,
                                    "baseline_relevance": b.relevances.get(cid),
                                    "arm_relevance": r.relevances.get(cid)})
    out["routing_agreement"] = {
        "compared": agree + disagree, "agree": agree, "disagree": disagree,
        "agreement_rate": round(agree / (agree + disagree), 4) if (agree + disagree) else None,
        "divergences": divergences[:60],
    }
    base_judge = sum((r.jev_input or 0) + (r.jev_output or 0) for r in baseline)
    out["savings_vs_baseline"] = {
        "judge_tokens_baseline": base_judge,
        "judge_tokens_arm": total_judge,
        "judge_tokens_saved": base_judge - total_judge,
        "judge_tokens_saved_pct": round(1 - total_judge / base_judge, 4) if base_judge else None,
        "reduction_factor": round(base_judge / total_judge, 2) if total_judge else None,
        "cost_saved_usd": round(cost_usd(base_judge, 0, "jev-1.13.0") -
                                cost_usd(total_judge, 0, "jev-1.13.0"), 6),
    }
    return out


def shadow_report(results: list[QuestionResult]) -> dict:
    """Aggregate the shadow-mode measurements that decide whether a risky flag may be promoted."""
    ze_agree = ze_dis = 0
    l3_agree = l3_dis = l3_sug = 0
    l3_err: list[float] = []
    neg_hits = 0
    layers = {"hits_l1": 0, "hits_l2": 0, "hits_l3": 0, "hits_l4": 0, "hits_l5": 0,
              "lookups": 0, "misses": 0}
    early_stops: dict[str, int] = {}
    inj_reasons: dict[str, int] = {}
    for r in results:
        m = r.metrics
        ze_agree += m.get("zero_evidence_agreements") or 0
        ze_dis += m.get("zero_evidence_disagreements") or 0
        cl = m.get("cache_layers") or {}
        for k in layers:
            layers[k] += cl.get(k) or 0
        neg_hits += cl.get("negative_hits") or 0
        l3_sug += cl.get("l3_suggested") or 0
        l3_agree += cl.get("l3_agreements") or 0
        l3_dis += cl.get("l3_disagreements") or 0
        if cl.get("l3_mean_abs_error") is not None:
            l3_err.append(cl["l3_mean_abs_error"])
        jd = m.get("jev") or {}
        for ev in (jd.get("shadow") or {}).get("early_stop") or []:
            early_stops[ev["reason"]] = early_stops.get(ev["reason"], 0) + 1
        for reason, n in ((jd.get("shadow") or {}).get("injection_skipped_reasons") or {}).items():
            inj_reasons[reason] = inj_reasons.get(reason, 0) + n
    ze_total = ze_agree + ze_dis
    l3_total = l3_agree + l3_dis
    return {
        "zero_evidence": {"agreements": ze_agree, "disagreements": ze_dis,
                          "precision": round(ze_agree / ze_total, 4) if ze_total else None,
                          # NEVER "safe_to_promote" from this signal alone. Agreement here only
                          # means the JUDGE also disliked the candidates the rule flagged, measured
                          # over the minority that survived the pre-filter into the paid pool. It
                          # says nothing about the candidates the rule would have dropped BEFORE
                          # they ever reached the judge, which is where the damage happens:
                          # scripts/validate_free_stages.py checks the rule against GROUND TRUTH
                          # over the whole candidate set and found it flags real answer notes.
                          # Promotion is gated on that check, not on this one.
                          "judge_agreement_only": True,
                          "verdict": ("judge_agrees" if ze_total and ze_dis == 0
                                      else "judge_disagrees" if ze_dis else "insufficient_data"),
                          "promotion_gate": "scripts/validate_free_stages.py::check_zero_evidence "
                                            "(ground truth), not this metric"},
        "cache_layers": layers,
        "cache_hit_rate": round((layers["hits_l1"] + layers["hits_l2"] + layers["hits_l3"]) /
                                layers["lookups"], 4) if layers["lookups"] else None,
        "negative_hits": neg_hits,
        "l3_fingerprint": {"suggested": l3_sug, "agreements": l3_agree, "disagreements": l3_dis,
                           "false_positive_rate": round(l3_dis / l3_total, 4) if l3_total else None,
                           "mean_abs_error": round(statistics.fmean(l3_err), 4) if l3_err else None,
                           "verdict": ("safe_to_promote" if l3_total >= 10 and l3_dis == 0
                                       else "unsafe" if l3_dis else "insufficient_data")},
        "early_stop_reasons": early_stops,
        "injection_skip_reasons": inj_reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Stacked JEV token-optimization benchmark")
    ap.add_argument("--questions", default=str(PROJECT_ROOT / "benchmark" / "synthetic_questions.json"))
    ap.add_argument("--vault", default=None,
                    help="vault directory for this run. Overrides MEMORY_GATEWAY_VAULT; accepts "
                         "absolute or relative paths. Defaults to the bundled data/synthetic_vault.")
    ap.add_argument("--arms", default="all", help="comma-separated arm names, or 'all'")
    ap.add_argument("--limit", type=int, default=0, help="first N questions only (0 = all)")
    ap.add_argument("--max-results", type=int, default=10)
    ap.add_argument("--two-pass", action="store_true",
                    help="run cache arms twice (cold + warm) and report both")
    ap.add_argument("--isolation", choices=("arm", "run", "none"), default="arm",
                    help="cache isolation policy. 'arm' (default) = every arm pays its own way, so "
                         "per-arm savings are attributable. 'run' = arms share a namespace (measures "
                         "the cache; use with --two-pass). 'none' = production namespace, may read "
                         "earlier runs — never valid for a comparison.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--dry-run", action="store_true", help="plan only, no API calls")
    args = ap.parse_args()

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.limit:
        questions = questions[:args.limit]

    arms_all = build_arms()
    names = list(arms_all) if args.arms == "all" else [a.strip() for a in args.arms.split(",")]
    unknown = [n for n in names if n not in arms_all]
    if unknown:
        print(f"unknown arms: {unknown}\navailable: {list(arms_all)}")
        return 2
    if "baseline" not in names:
        names.insert(0, "baseline")   # every comparison needs it, and it must run first (§27)

    passes = 2 if args.two_pass else 1
    print(f"questions={len(questions)} arms={names} passes={passes}")
    if args.dry_run:
        print("dry run: no API calls made")
        return 0

    from config.retrieval import RetrievalConfig, resolve_vault_path, validate_vault_path
    from app.gateway.memory_gateway import MemoryGateway

    rc = RetrievalConfig()
    rc.vault_path = validate_vault_path(resolve_vault_path(args.vault))
    gw = MemoryGateway(retrieval_cfg=rc)
    # Caches must be LIVE for this benchmark. `cache_enabled` is a derived property: it is False
    # whenever benchmark_mode is on or the profile is "benchmark" (correct for pipeline comparison,
    # and exactly wrong for measuring a cache), so the inputs are set rather than the property.
    gw.bench_cfg.benchmark_mode = False
    gw.bench_cfg.profile = "production"
    gw.bench_cfg.cache_enabled_env = True
    if not gw.bench_cfg.cache_enabled:
        print("FATAL: caches are disabled; a cache arm cannot be measured. Check PROFILE/CACHE_ENABLED.")
        return 3
    # The graph must come from the vault under test. GraphifyService derives its path from the
    # configured mirror dir, which still points at the real vault's mirror, so a synthetic-corpus run
    # would silently be scored against the WRONG graph — graph-only candidates for notes that do not
    # exist in this vault. Point it at the corpus's own graph when one ships with it.
    local_graph = Path(rc.vault_path) / "graphify-out" / "graph.json"
    if local_graph.exists():
        gw.graph_index.path = local_graph
    gw.warm()
    gw.graph_index.load()
    print(f"vault={gw.vault.root} notes={len(gw.vault.list_markdown())} "
          f"sections={gw.baseline.sections_indexed}")
    print(f"graph={gw.graph_index.path} nodes={len(gw.graph_index.nodes)} "
          f"loaded={gw.graph_index.loaded}")
    if not gw.graph_index.loaded:
        print("FATAL: graph not loaded — the hybrid retriever would degrade silently.")
        return 3

    session_id = f"opt-{time.strftime('%Y%m%d-%H%M%S')}"
    print(f"cache isolation = {args.isolation}")
    gw.db.create_session(session_id, "opt_benchmark",
                         {"arms": names, "questions": len(questions), "passes": passes,
                          "isolation": args.isolation})

    def namespace_for(arm: str) -> str:
        """Namespace applied while an arm runs. See the module docstring for why this matters."""
        if args.isolation == "none":
            return ""
        if args.isolation == "run":
            return session_id
        return f"{session_id}:{arm}"

    all_results: dict[str, list[QuestionResult]] = {}
    per_pass: dict[str, dict[int, list[QuestionResult]]] = {}
    for arm in names:
        opt = arms_all[arm]
        gw.cache_namespace = namespace_for(arm)
        gw.jev = gw.make_jev(gw.jev_cfg)     # rebuild so the flat cache path sees the namespace
        n_passes = passes if (arm in CACHE_ARMS and passes > 1) else 1
        per_pass[arm] = {}
        for p in range(1, n_passes + 1):
            print(f"\n== arm {arm} (pass {p}/{n_passes}) ns={gw.cache_namespace!r} ==")
            res = run_arm(gw, arm, opt, questions, pass_no=p, max_results=args.max_results,
                          session_id=session_id, progress=print)
            per_pass[arm][p] = res
        # Headline figures use the FIRST (cold) pass: it is the attributable cost of the arm's own
        # mechanisms. The warm pass is reported separately as the cache's contribution, never merged
        # into the arm's total — that conflation is what made an earlier run report 0 judge tokens.
        all_results[arm] = per_pass[arm][1]

    base = all_results["baseline"]
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_id": session_id,
        "dataset": {"questions_file": args.questions, "questions": len(questions),
                    "vault": str(gw.vault.root), "notes": len(gw.vault.list_markdown()),
                    "sections_indexed": gw.baseline.sections_indexed},
        "config": {"jev": gw.jev_cfg.__dict__, "max_results": args.max_results,
                   "prefilter_top_k": gw.retrieval_cfg.prefilter_top_k,
                   "prefilter_lexical_weight": gw.retrieval_cfg.prefilter_lexical_weight,
                   "passes": passes},
        "arms": {},
        "stack": [],
        "shadow": {},
        "per_question": {},
    }
    for arm in names:
        summary = summarize(arm, all_results[arm], None if arm == "baseline" else base)
        summary["flags"] = arms_all[arm].active_flags()
        if len(per_pass[arm]) > 1:
            # The WARM pass: same arm, same questions, cache populated. Reported as the cache's own
            # contribution, alongside the cold figure, never instead of it.
            summary["warm_pass"] = summarize(f"{arm}#warm", per_pass[arm][2],
                                             None if arm == "baseline" else base)
        report["arms"][arm] = summary
        report["shadow"][arm] = shadow_report(all_results[arm])
        report["per_question"][arm] = [r.to_dict() for r in all_results[arm]]
        report["stack"].append({
            "arm": arm,
            "judge_tokens": summary["judge_tokens_total"],
            "judge_tokens_warm": summary.get("warm_pass", {}).get("judge_tokens_total"),
            "context_tokens": summary["context_tokens_total"],
            "amplification": summary["amplification_overall"],
            "recall_mean": summary["recall"]["mean"],
            "jev_calls": summary["jev_calls_total"],
            "relevance_questions": summary["relevance_questions_total"],
            "cost_usd": summary["cost_usd_total"],
            "recall_regressions": summary.get("recall_vs_baseline", {}).get("questions_regressed_n"),
            "routing_agreement": summary.get("routing_agreement", {}).get("agreement_rate"),
        })

    out = Path(args.out or PROJECT_ROOT / "reports" / f"opt_stack_{time.strftime('%Y-%m-%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    base_judge = report["stack"][0]["judge_tokens"] or 1
    print("\n" + "=" * 118)
    print(f"{'arm':<22}{'judge_tok':>10}{'vs_base':>9}{'warm':>9}{'ctx_tok':>9}{'amp':>7}"
          f"{'recall':>8}{'calls':>7}{'rel_q':>7}{'agree':>8}{'regr':>6}{'cost$':>10}")
    print("-" * 118)
    for row in report["stack"]:
        delta = row["judge_tokens"] / base_judge - 1
        warm = row["judge_tokens_warm"]
        print(f"{row['arm']:<22}{row['judge_tokens']:>10}{delta:>+8.1%}"
              f"{(str(warm) if warm is not None else '-'):>9}{row['context_tokens']:>9}"
              f"{str(row['amplification']):>7}{str(row['recall_mean']):>8}{row['jev_calls']:>7}"
              f"{row['relevance_questions']:>7}{str(row['routing_agreement']):>8}"
              f"{str(row['recall_regressions']):>6}{row['cost_usd']:>10.5f}")
    print("=" * 118)
    print(f"isolation={args.isolation}  (judge_tok is the COLD, attributable cost of each arm)")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
