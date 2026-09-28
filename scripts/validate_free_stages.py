"""Validate the FREE cascade stages against ground truth — zero API calls, zero cost.

Nothing here talks to the paid judge. The point is to answer, before spending a cent:

  1. NEAR-DUP DETECTION: does the clusterer find the 60 duplicate groups the corpus manifest
     declares, and does it invent any that are not there? (precision/recall of clustering)
  2. RETRIEVAL RECALL BY K: at what top-K does the deterministic ranker still contain every
     expected source? This is the hard ceiling on how small adaptive-K may ever go — no judge
     behaviour can rescue a note the ranker never sent.
  3. ADAPTIVE-K SAFETY: for each question, compare the K the planner chose against the rank the
     ground-truth note actually landed at. A plan that selects fewer candidates than the answer's
     position is a guaranteed recall loss, and must be caught here rather than in a paid benchmark.
  4. ZERO-EVIDENCE SAFETY: does the zero-evidence rule ever flag a ground-truth note? One hit means
     the rule can never be promoted out of shadow mode.
  5. INJECTION SCREEN: does it catch all 6 malicious notes in the manifest (recall must be 1.0),
     and how many benign notes does it also flag (the price we accept)?
  6. SMART SNIPPET: does query-aware extraction preserve the buried fact token that a prefix cut
     would lose, across snippet budgets? This is the measurement that decides whether snippet
     reduction is safe at all.

Everything prints a number. Anything that cannot be measured prints UNAVAILABLE instead of a guess.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.optimization import OptimizationConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.services import adaptive as ad  # noqa: E402
from app.services.injection_screen import screen  # noqa: E402
from app.services.near_dup import cluster_near_duplicates, similarity  # noqa: E402
from app.services.prefilter import rank  # noqa: E402
from app.services.query_fp import classify, fingerprint, term_key  # noqa: E402
from app.services.snippet import extract  # noqa: E402

VAULT = PROJECT_ROOT / "data" / "synthetic_vault"
QUESTIONS = PROJECT_ROOT / "benchmark" / "synthetic_questions.json"


def load():
    manifest = json.loads((VAULT / "MANIFEST.json").read_text(encoding="utf-8"))
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return manifest, questions


# ---------------------------------------------------------------------------------------------
def check_near_dup(manifest: dict, threshold: float) -> dict:
    """Cluster the DECLARED duplicate groups plus a control set of unrelated notes."""
    from app.schemas.models import Candidate

    groups = [g for g in manifest["duplicate_groups"] if len(g) >= 2]
    dup_paths = {p for g in groups for p in g}
    truth: dict[str, int] = {}
    for gi, g in enumerate(groups):
        for p in g:
            truth[p] = gi

    # Controls: notes in no duplicate group at all. Included so a clusterer that merges everything
    # is caught — recall alone cannot distinguish "found the duplicates" from "merged the corpus".
    controls = [p for p in sorted(manifest["facts"], key=lambda f: f["path"])
                if p["path"] not in dup_paths][:120]
    control_paths = [c["path"] for c in controls]

    cands = []
    for i, p in enumerate(sorted(dup_paths) + control_paths):
        text = (VAULT / p).read_text(encoding="utf-8")
        cands.append(Candidate(candidate_id=f"c{i:04d}", source_file=p, section="",
                               snippet=text, score=1.0 - i * 1e-4, content_hash=f"h{i}"))

    clusters, metrics = cluster_near_duplicates(cands, threshold=threshold)
    # Map each candidate to the cluster it ended in.
    got: dict[str, int] = {}
    for ci, cl in enumerate(clusters):
        for member in [cl.rep, *cl.members]:
            got[member.source_file] = ci

    # Pair-level precision/recall over every pair of the evaluated set.
    paths = [c.source_file for c in cands]
    tp = fp = fn = 0
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            same_truth = truth.get(paths[i], -1) == truth.get(paths[j], -2)
            same_got = got.get(paths[i]) == got.get(paths[j])
            if same_truth and same_got:
                tp += 1
            elif same_got and not same_truth:
                fp += 1
            elif same_truth and not same_got:
                fn += 1
    missed = []
    for g in groups:
        ids = {got.get(p) for p in g}
        if len(ids) > 1:
            sims = [round(similarity((VAULT / g[0]).read_text(encoding="utf-8"),
                                     (VAULT / p).read_text(encoding="utf-8")), 4) for p in g[1:]]
            missed.append({"group": g, "similarity_to_first": sims})
    return {
        "declared_groups": len(groups),
        "notes_in_groups": len(dup_paths),
        "control_notes": len(control_paths),
        "clusters_formed": metrics["dedup_near_clusters"],
        "collapsed": metrics["dedup_near_collapsed"],
        "pair_true_positives": tp, "pair_false_positives": fp, "pair_false_negatives": fn,
        "pair_precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "pair_recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        "groups_not_fully_merged": len(missed),
        "groups_not_fully_merged_detail": missed[:10],
    }


# ---------------------------------------------------------------------------------------------
def check_retrieval(gw, questions: list[dict], rc: RetrievalConfig) -> dict:
    """Rank of each expected source under the deterministic hybrid ranker."""
    from app.retrieval.pipelines import _graphify_candidates

    ks = (2, 3, 4, 6, 8, 10, 12, 16, 20, 25, 50)
    hits = {k: 0 for k in ks}
    total = 0
    positions: list[int] = []
    unreachable: list[dict] = []
    per_q: list[dict] = []
    for q in questions:
        exp = q.get("expected_sources") or []
        if not exp:
            continue
        uniq, _ = _graphify_candidates(gw, q["question"])
        ordered = rank(q["question"], uniq, rc.prefilter_lexical_weight)
        files = [c.source_file for c in ordered]
        worst = -1
        for e in exp:
            total += 1
            pos = files.index(e) if e in files else None
            if pos is None:
                unreachable.append({"qid": q["id"], "source": e, "pool": len(files)})
                worst = 10**6
                continue
            positions.append(pos)
            worst = max(worst, pos)
            for k in ks:
                if pos < k:
                    hits[k] += 1
        per_q.append({"qid": q["id"], "qclass": q.get("qclass"), "expected": len(exp),
                      "worst_rank": worst if worst < 10**6 else None,
                      "pool": len(files)})
    return {
        "questions_with_expected": len([q for q in questions if q.get("expected_sources")]),
        "expected_sources_total": total,
        "recall_at_k": {k: round(hits[k] / total, 4) for k in ks} if total else {},
        "rank_position": {
            "mean": round(statistics.fmean(positions), 2) if positions else None,
            "median": statistics.median(positions) if positions else None,
            "p90": (sorted(positions)[int(len(positions) * 0.9)] if positions else None),
            "max": max(positions) if positions else None,
        },
        "unreachable": unreachable,
        "unreachable_n": len(unreachable),
        "per_question": per_q,
    }


# ---------------------------------------------------------------------------------------------
def check_adaptive_k(gw, questions: list[dict], rc: RetrievalConfig, opt: OptimizationConfig) -> dict:
    """Does the planned K cover the position the answer actually landed at?"""
    from app.retrieval.pipelines import _graphify_candidates

    rows = []
    unsafe = []
    ks: list[int] = []
    for q in questions:
        exp = q.get("expected_sources") or []
        uniq, _ = _graphify_candidates(gw, q["question"])
        ordered = rank(q["question"], uniq, rc.prefilter_lexical_weight)
        profile = classify(q["question"])
        conf = ad.rank_confidence(q["question"], ordered, rc.prefilter_lexical_weight)
        plan = ad.plan_k(profile, conf, max_total=min(opt.adaptive_k_max, len(ordered) or 1))
        waves = plan.waves()
        files = [c.source_file for c in ordered]
        worst = max((files.index(e) for e in exp if e in files), default=None)
        ks.append(waves[-1])
        row = {"qid": q["id"], "qclass": q.get("qclass"), "complexity": profile.complexity,
               "rank_confident": conf.confident, "start": plan.start, "waves": waves,
               "max_k": waves[-1], "answer_worst_rank": worst, "reason": plan.reason}
        rows.append(row)
        # Unsafe = the escalation ceiling still sits below the answer's position.
        if worst is not None and worst >= waves[-1]:
            unsafe.append(row)
    fixed = rc.prefilter_top_k
    starts = [r["start"] for r in rows]
    return {
        "fixed_k_baseline": fixed,
        # WAVE 1 is what is actually paid for on every query; the ceiling is only reached when the
        # early-stop check refuses to stop, so comparing ceilings to the fixed K would overstate
        # the cost and understate the saving. Both are reported.
        "wave1_k_mean": round(statistics.fmean(starts), 2) if starts else None,
        "wave1_k_median": statistics.median(starts) if starts else None,
        "wave1_saved_vs_fixed_k": sum(max(0, fixed - s) for s in starts),
        "wave1_added_vs_fixed_k": sum(max(0, s - fixed) for s in starts),
        "ceiling_k_mean": round(statistics.fmean(ks), 2) if ks else None,
        "ceiling_k_median": statistics.median(ks) if ks else None,
        "ceiling_k_max": max(ks) if ks else None,
        "ceiling_saved_vs_fixed_k": sum(max(0, fixed - k) for k in ks),
        "ceiling_added_vs_fixed_k": sum(max(0, k - fixed) for k in ks),
        "unsafe_plans": unsafe,
        "unsafe_plans_n": len(unsafe),
        "wave1_by_complexity": {
            c: round(statistics.fmean([r["start"] for r in rows if r["complexity"] == c]), 2)
            for c in sorted({r["complexity"] for r in rows})},
        "ceiling_by_complexity": {
            c: round(statistics.fmean([r["max_k"] for r in rows if r["complexity"] == c]), 2)
            for c in sorted({r["complexity"] for r in rows})},
        "per_question": rows,
    }


# ---------------------------------------------------------------------------------------------
def check_zero_evidence(gw, questions: list[dict], rc: RetrievalConfig) -> dict:
    """A ground-truth note must NEVER be flagged. One hit blocks promotion permanently."""
    from app.retrieval.pipelines import _graphify_candidates

    flagged_total = 0
    considered = 0
    violations = []
    for q in questions:
        exp = set(q.get("expected_sources") or [])
        uniq, _ = _graphify_candidates(gw, q["question"])
        ordered = rank(q["question"], uniq, rc.prefilter_lexical_weight)
        considered += len(ordered)
        flagged = ad.zero_evidence(q["question"], ordered)
        flagged_total += len(flagged)
        for c in flagged:
            if c.source_file in exp:
                violations.append({"qid": q["id"], "source": c.source_file,
                                   "question": q["question"]})
    return {
        "candidates_considered": considered,
        "flagged": flagged_total,
        "flagged_share": round(flagged_total / considered, 4) if considered else None,
        "ground_truth_flagged": len(violations),
        "violations": violations[:20],
        "verdict": "safe_for_shadow_only" if violations else "no_ground_truth_loss_observed",
    }


# ---------------------------------------------------------------------------------------------
def check_injection(manifest: dict) -> dict:
    mal = manifest["injection_notes"]["malicious"]
    ben = manifest["injection_notes"]["benign"]
    others = [f["path"] for f in manifest["facts"]
              if f["path"] not in set(mal) | set(ben)][:200]
    caught = [p for p in mal if screen((VAULT / p).read_text(encoding="utf-8")).suspicious]
    ben_flagged = [p for p in ben if screen((VAULT / p).read_text(encoding="utf-8")).suspicious]
    other_flagged = [p for p in others if screen((VAULT / p).read_text(encoding="utf-8")).suspicious]
    return {
        "malicious_total": len(mal), "malicious_caught": len(caught),
        "malicious_recall": round(len(caught) / len(mal), 4) if mal else None,
        "malicious_missed": [p for p in mal if p not in caught],
        "benign_total": len(ben), "benign_flagged": len(ben_flagged),
        "ordinary_notes_checked": len(others), "ordinary_flagged": len(other_flagged),
        "false_flag_rate_ordinary": round(len(other_flagged) / len(others), 4) if others else None,
        "verdict": ("safe: catches every malicious note" if len(caught) == len(mal)
                    else "UNSAFE: missed malicious notes, do not gate on this screen"),
    }


# ---------------------------------------------------------------------------------------------
def check_snippets(manifest: dict, questions: list[dict]) -> dict:
    """Can a reduced snippet still contain the fact, if it is chosen query-aware?"""
    facts = {f["path"]: f for f in manifest["facts"]}
    budgets = (300, 240, 180, 120, 90, 60)
    rows = {b: {"focused_kept": 0, "prefix_kept": 0, "n": 0} for b in budgets}
    examples = []
    for q in questions:
        for path in q.get("expected_sources") or []:
            fact = facts.get(path)
            if not fact:
                continue
            token = fact["token"]
            text = (VAULT / path).read_text(encoding="utf-8")
            if token not in text:
                continue
            for b in budgets:
                res = extract(text, q["question"], b)
                # The naive alternative this replaces: a blind prefix cut of the same token budget.
                prefix = text[: b * 4]
                rows[b]["n"] += 1
                rows[b]["focused_kept"] += int(token in res.text)
                rows[b]["prefix_kept"] += int(token in prefix)
            if len(examples) < 5:
                r = extract(text, q["question"], 120)
                examples.append({"qid": q["id"], "token": token, "strategy": r.strategy,
                                 "kept_at_120": token in r.text,
                                 "prefix_kept_at_120": token in text[:480]})
    out = {}
    for b in budgets:
        n = rows[b]["n"]
        out[b] = {"samples": n,
                  "query_aware_fact_retention": round(rows[b]["focused_kept"] / n, 4) if n else None,
                  "prefix_cut_fact_retention": round(rows[b]["prefix_kept"] / n, 4) if n else None}
    return {"by_budget": out, "examples": examples}


# ---------------------------------------------------------------------------------------------
def check_cache_keys(questions: list[dict]) -> dict:
    """Do the declared paraphrase pairs actually collapse onto the same cache key?"""
    by_id = {q["id"]: q for q in questions}
    pairs = [(q, by_id[q["paraphrase_of"]]) for q in questions
             if q.get("paraphrase_of") and q["paraphrase_of"] in by_id]
    l2 = sum(1 for a, b in pairs if term_key(a["question"]) == term_key(b["question"]))
    l3 = sum(1 for a, b in pairs if fingerprint(a["question"]) == fingerprint(b["question"]))
    misses = [{"a": a["question"], "b": b["question"],
               "a_terms": sorted(term_key(a["question"])), "b_terms": sorted(term_key(b["question"]))}
              for a, b in pairs if fingerprint(a["question"]) != fingerprint(b["question"])]
    # Collisions are the danger of a loose key: two DIFFERENT questions sharing a fingerprint.
    fps: dict[tuple, list[str]] = {}
    for q in questions:
        fps.setdefault(fingerprint(q["question"]), []).append(q["id"])
    para = {frozenset((q["id"], q["paraphrase_of"])) for q in questions if q.get("paraphrase_of")}
    collisions = [ids for fp, ids in fps.items() if len(ids) > 1
                  and not any(frozenset(p) <= set(ids) for p in para)]
    return {
        "paraphrase_pairs": len(pairs),
        "l2_term_key_matches": l2,
        "l3_fingerprint_matches": l3,
        "l2_hit_rate": round(l2 / len(pairs), 4) if pairs else None,
        "l3_hit_rate": round(l3 / len(pairs), 4) if pairs else None,
        "l3_unexpected_collisions": collisions,
        "l3_unexpected_collisions_n": len(collisions),
        "pairs_not_collapsed": misses[:10],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Free-stage validation against ground truth (no API calls)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--skip-retrieval", action="store_true",
                    help="skip the stages that need a warmed index")
    args = ap.parse_args()

    manifest, questions = load()
    if args.limit:
        questions = questions[:args.limit]
    opt = OptimizationConfig.all_on()
    t0 = time.perf_counter()
    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "vault": str(VAULT), "notes": manifest["notes"],
                    "questions": len(questions), "api_calls": 0,
                    "config": {"near_dedup_threshold": opt.near_dedup_threshold,
                               "adaptive_k_max": opt.adaptive_k_max,
                               "opt_version": opt.version}}

    print(f"== near-duplicate clustering vs manifest (threshold={opt.near_dedup_threshold}) ==")
    report["near_dup"] = check_near_dup(manifest, opt.near_dedup_threshold)
    print(json.dumps({k: v for k, v in report["near_dup"].items()
                      if not k.endswith("detail")}, indent=2))

    print("\n== injection screen vs manifest ==")
    report["injection_screen"] = check_injection(manifest)
    print(json.dumps(report["injection_screen"], indent=2))

    print("\n== cache key collapse on declared paraphrases ==")
    report["cache_keys"] = check_cache_keys(questions)
    print(json.dumps({k: v for k, v in report["cache_keys"].items()
                      if k != "pairs_not_collapsed"}, indent=2))

    print("\n== query-aware snippet vs prefix cut ==")
    report["snippets"] = check_snippets(manifest, questions)
    print(json.dumps(report["snippets"]["by_budget"], indent=2))

    if not args.skip_retrieval:
        from app.gateway.memory_gateway import MemoryGateway

        rc = RetrievalConfig()
        rc.vault_path = VAULT
        gw = MemoryGateway(retrieval_cfg=rc)
        gw.baseline.build()
        gw.graph_index.path = VAULT / "graphify-out" / "graph.json"
        gw.graph_index.load()
        print(f"\nindexed sections={gw.baseline.sections_indexed} "
              f"graph_nodes={len(gw.graph_index.nodes)} loaded={gw.graph_index.loaded}")

        print("\n== deterministic retrieval recall@K ==")
        report["retrieval"] = check_retrieval(gw, questions, rc)
        print(json.dumps({k: v for k, v in report["retrieval"].items()
                          if k not in ("per_question", "unreachable")}, indent=2))

        print("\n== adaptive-K safety vs answer position ==")
        report["adaptive_k"] = check_adaptive_k(gw, questions, rc, opt)
        print(json.dumps({k: v for k, v in report["adaptive_k"].items()
                          if k not in ("per_question", "unsafe_plans")}, indent=2))
        print(f"unsafe plans: {report['adaptive_k']['unsafe_plans_n']}")

        print("\n== zero-evidence rule vs ground truth ==")
        report["zero_evidence"] = check_zero_evidence(gw, questions, rc)
        print(json.dumps({k: v for k, v in report["zero_evidence"].items()
                          if k != "violations"}, indent=2))

    report["elapsed_s"] = round(time.perf_counter() - t0, 1)
    out = Path(args.out or PROJECT_ROOT / "reports" /
               f"free_stage_validation_{time.strftime('%Y-%m-%d_%H%M')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nreport: {out}  ({report['elapsed_s']}s, 0 API calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
