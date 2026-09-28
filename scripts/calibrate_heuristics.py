"""Calibrate the free heuristics against ground truth (no API calls).

Three knobs cannot be chosen by reasoning, only by measurement:

  1. near-dup threshold — precision/recall of clustering vs the manifest's 60 declared groups.
  2. rank-confidence signal — which cheap signal actually predicts "the answer is at rank 0"?
  3. adaptive-K ceiling — the smallest ceiling that still covers every answer's real position.

Each section prints a sweep, so the value committed to the code is traceable to a table.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from config.retrieval import RetrievalConfig  # noqa: E402
from app.schemas.models import Candidate  # noqa: E402
from app.services.near_dup import cluster_near_duplicates  # noqa: E402
from app.services.prefilter import lexical_overlap, rank, terms  # noqa: E402
from app.services.query_fp import classify  # noqa: E402

VAULT = PROJECT_ROOT / "data" / "synthetic_vault"
QUESTIONS = PROJECT_ROOT / "benchmark" / "synthetic_questions.json"


def sweep_near_dup() -> None:
    manifest = json.loads((VAULT / "MANIFEST.json").read_text(encoding="utf-8"))
    groups = [g for g in manifest["duplicate_groups"] if len(g) >= 2]
    dup_paths = sorted({p for g in groups for p in g})
    truth = {p: gi for gi, g in enumerate(groups) for p in g}
    controls = [f["path"] for f in manifest["facts"] if f["path"] not in set(dup_paths)][:120]

    cands = []
    for i, p in enumerate(dup_paths + controls):
        cands.append(Candidate(candidate_id=f"c{i:04d}", source_file=p, section="",
                               snippet=(VAULT / p).read_text(encoding="utf-8"),
                               score=1.0 - i * 1e-4, content_hash=f"h{i}"))
    paths = [c.source_file for c in cands]

    print("\n== near-dup threshold sweep ==")
    print(f"{'thr':>6}{'clusters':>10}{'collapsed':>11}{'TP':>6}{'FP':>5}{'FN':>5}"
          f"{'prec':>8}{'recall':>8}{'F1':>8}")
    for thr in (0.99, 0.97, 0.95, 0.92, 0.90, 0.88, 0.85, 0.82, 0.80, 0.75, 0.70):
        fresh = [Candidate(candidate_id=c.candidate_id, source_file=c.source_file, section="",
                           snippet=c.snippet, score=c.score, content_hash=c.content_hash)
                 for c in cands]
        clusters, m = cluster_near_duplicates(fresh, threshold=thr)
        got = {mem.source_file: ci for ci, cl in enumerate(clusters) for mem in [cl.rep, *cl.members]}
        tp = fp = fn = 0
        for i in range(len(paths)):
            for j in range(i + 1, len(paths)):
                same_t = truth.get(paths[i], -1) == truth.get(paths[j], -2)
                same_g = got.get(paths[i]) == got.get(paths[j])
                tp += same_t and same_g
                fp += same_g and not same_t
                fn += same_t and not same_g
        prec = tp / (tp + fp) if (tp + fp) else 1.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        print(f"{thr:>6.2f}{m['dedup_near_clusters']:>10}{m['dedup_near_collapsed']:>11}"
              f"{tp:>6}{fp:>5}{fn:>5}{prec:>8.4f}{rec:>8.4f}{f1:>8.4f}")


def sweep_confidence_and_k() -> None:
    from app.gateway.memory_gateway import MemoryGateway
    from app.retrieval.pipelines import _graphify_candidates
    from app.services.prefilter import normalize_scores

    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    rc = RetrievalConfig()
    rc.vault_path = VAULT
    gw = MemoryGateway(retrieval_cfg=rc)
    gw.baseline.build()
    gw.graph_index.path = VAULT / "graphify-out" / "graph.json"
    gw.graph_index.load()
    w = rc.prefilter_lexical_weight

    rows = []
    for q in questions:
        exp = q.get("expected_sources") or []
        uniq, _ = _graphify_candidates(gw, q["question"])
        ordered = rank(q["question"], uniq, w)
        if not ordered:
            continue
        qt = terms(q["question"])
        norm = normalize_scores(ordered)
        lex = [lexical_overlap(qt, c) for c in ordered]
        pct = [norm.get(c.candidate_id, 0.0) for c in ordered]
        comb = [(1 - w) * pct[i] + w * lex[i] for i in range(len(ordered))]
        files = [c.source_file for c in ordered]
        worst = max((files.index(e) for e in exp if e in files), default=None)
        rows.append({
            "qid": q["id"], "qclass": q.get("qclass"),
            "complexity": classify(q["question"]).complexity,
            "n": len(ordered), "worst": worst,
            # candidate signals for "is the ranker decisive?"
            "comb_margin": comb[0] - (comb[1] if len(comb) > 1 else 0.0),
            "lex_top": lex[0],
            "lex_margin": lex[0] - (max(lex[1:]) if len(lex) > 1 else 0.0),
            "lex_second_best": (max(lex[1:]) if len(lex) > 1 else 0.0),
            "n_with_full_lex": sum(1 for v in lex if v >= 0.999),
            "score_top": ordered[0].score or 0.0,
            "score_margin": (ordered[0].score or 0.0) - (ordered[1].score or 0.0 if len(ordered) > 1 else 0.0),
        })

    at0 = [r for r in rows if r["worst"] == 0]
    deep = [r for r in rows if r["worst"] is not None and r["worst"] >= 8]
    print(f"\n== confidence signals: {len(rows)} questions, {len(at0)} answered at rank 0, "
          f"{len(deep)} with answer at rank >= 8 ==")
    for sig in ("comb_margin", "lex_top", "lex_margin", "lex_second_best", "n_with_full_lex",
                "score_margin"):
        a = [r[sig] for r in at0]
        d = [r[sig] for r in deep]
        print(f"{sig:>18}  rank0 mean={statistics.fmean(a):>8.4f} median={statistics.median(a):>8.4f}"
              f"   deep mean={statistics.fmean(d) if d else float('nan'):>8.4f}"
              f" median={statistics.median(d) if d else float('nan'):>8.4f}")

    print("\n== candidate confidence rules: does 'confident' really mean rank 0? ==")
    print(f"{'rule':>44}{'fires':>7}{'precision':>11}{'coverage':>10}")
    rules = {
        "comb_margin>=0.15 (current)": lambda r: r["comb_margin"] >= 0.15,
        "lex_top>=0.99 and unique full-lex": lambda r: r["lex_top"] >= 0.999 and r["n_with_full_lex"] == 1,
        "lex_top>=0.99 and lex_margin>=0.30": lambda r: r["lex_top"] >= 0.999 and r["lex_margin"] >= 0.30,
        "lex_top>=0.80 and lex_margin>=0.25": lambda r: r["lex_top"] >= 0.80 and r["lex_margin"] >= 0.25,
        "lex_top>=0.60 and lex_margin>=0.20": lambda r: r["lex_top"] >= 0.60 and r["lex_margin"] >= 0.20,
        "lex_margin>=0.40": lambda r: r["lex_margin"] >= 0.40,
        "lex_margin>=0.30": lambda r: r["lex_margin"] >= 0.30,
    }
    scored = [r for r in rows if r["worst"] is not None]
    for name, fn in rules.items():
        fired = [r for r in scored if fn(r)]
        correct = [r for r in fired if r["worst"] == 0]
        prec = len(correct) / len(fired) if fired else float("nan")
        cov = len(fired) / len(scored) if scored else 0.0
        print(f"{name:>44}{len(fired):>7}{prec:>11.4f}{cov:>10.4f}")

    print("\n== answer position by class (what ceiling each class really needs) ==")
    print(f"{'class':>14}{'n':>5}{'max_rank':>10}{'p95':>6}{'mean':>8}")
    for cls in sorted({r["qclass"] for r in scored}):
        sub = sorted(r["worst"] for r in scored if r["qclass"] == cls)
        p95 = sub[min(len(sub) - 1, int(len(sub) * 0.95))]
        print(f"{cls:>14}{len(sub):>5}{max(sub):>10}{p95:>6}{statistics.fmean(sub):>8.2f}")
    print(f"\n{'complexity':>14}{'n':>5}{'max_rank':>10}{'p95':>6}{'mean':>8}")
    for cls in sorted({r["complexity"] for r in scored}):
        sub = sorted(r["worst"] for r in scored if r["complexity"] == cls)
        p95 = sub[min(len(sub) - 1, int(len(sub) * 0.95))]
        print(f"{cls:>14}{len(sub):>5}{max(sub):>10}{p95:>6}{statistics.fmean(sub):>8.2f}")

    print("\n== recall@K by complexity (the ceiling each class needs) ==")
    print(f"{'complexity':>14}" + "".join(f"{k:>7}" for k in (2, 3, 4, 6, 8, 10, 12, 16, 20, 25)))
    for cls in sorted({r["complexity"] for r in scored}):
        sub = [r["worst"] for r in scored if r["complexity"] == cls]
        line = f"{cls:>14}"
        for k in (2, 3, 4, 6, 8, 10, 12, 16, 20, 25):
            line += f"{sum(1 for x in sub if x < k) / len(sub):>7.3f}"
        print(line)

    Path(PROJECT_ROOT / "reports" / "calibration_rows.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    sweep_near_dup()
    sweep_confidence_and_k()
