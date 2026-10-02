"""Check the ~300-token snippet JEV would receive, for either pipeline, without calling the judge
(§5.5, Parte 2b).

`--path frozen` reuses the REAL pipeline internals (app.retrieval.pipelines._graphify_candidates +
the real app.services.prefilter.prefilter) so the snippet inspected here is byte-for-byte what
run_graphify_jev would send: same BM25 seeds, same graph expansion (allow_ppr=False, matching the
frozen pipeline), same preprocess() truncation to RetrievalConfig.snippet_max_tokens, same prefilter
ranking and top_k cut. This path, and `app.services.dedup.preprocess`, are FROZEN (§5.5) — never
touch them to make this check pass.

`--path opt` reuses app.retrieval.pipelines_opt.select_pool — the exact free-stage cascade
(candidates -> smart snippet via `snippet.extract`/`fit_or_keep` -> ranking -> dedup -> zero-evidence
shadow -> adaptive-K) that `graphify_jev_opt` runs before ever calling the judge, under the same
OptimizationConfig.default_cascade() production uses. Same `extract()` call, same token budget,
stopped right before the PAID stage.

For each target question (q05, q07, q10 by default) reports:
  - whether a candidate from the expected source survived the pre-filter cut (i.e. would reach JEV)
  - which section of that note was chosen and how many tokens its snippet holds
  - whether the snippet text contains the expected evidence (terms from answer_hint)
  - where in the FULL note that evidence actually lives (which section, by line), so a "snippet
    picked the wrong section" failure is visible even when the right FILE survived the pre-filter

No LLM call, no network: pure deterministic re-run of the retrieval + pre-filter (or cascade) stages.
Candidate generation is the expensive part and never changes while the vault does, so it goes
through `scripts/_candidate_cache.py`; `--no-cache` forces the full re-run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("MEMORY_GATEWAY_VAULT", str(PROJECT_ROOT / "data" / "synthetic_vault"))

from config.benchmark import BenchmarkConfig  # noqa: E402
from config.optimizer import OptimizerConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.gateway.token_budget import estimate_tokens  # noqa: E402
from app.retrieval.graphify_hybrid import GraphIndex  # noqa: E402
from app.services.obsidian import split_sections  # noqa: E402
from app.services.prefilter import prefilter, terms  # noqa: E402
from scripts._candidate_cache import cached_candidates  # noqa: E402

DEFAULT_QIDS = ("q05", "q07", "q10")
DEFAULT_MAX_RESULTS = 10  # matches app.gateway.memory_gateway.MemoryGateway.search default


def _ensure_fresh_graph(gw: MemoryGateway, vault: Path) -> None:
    """Guard against a stale data/vault_mirror graph from a previous vault (see scripts/bench_ppr.py
    for the full explanation: `warm()` swallows a failed `graphify update`, and the mirror path is
    shared across vaults, so a silent failure would otherwise make this check inspect the WRONG
    note's snippet without any error).
    """
    gw.graph_index.load()
    sample = (gw.graph_index.nodes[0].get("source_file") if gw.graph_index.nodes else None)
    if sample and not (vault / str(sample).replace("\\", "/")).exists():
        gw.graphify.build(force=True)
        gw.graph_index.load()


def make_gw(vault: Path) -> MemoryGateway:
    import tempfile
    rc = RetrievalConfig(vault_path=vault)
    bc = BenchmarkConfig(db_path=str(Path(tempfile.mkdtemp()) / "b.db"), profile="benchmark")
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=OptimizerConfig.disabled())
    g = vault / "graphify-out" / "graph.json"
    if g.exists():
        gw.graph_index = GraphIndex(g)
    gw.warm()
    if not g.exists():
        _ensure_fresh_graph(gw, vault)
    return gw


def evidence_terms(q: dict) -> set[str]:
    """Distinctive terms an evidence-bearing snippet must contain, from answer_hint (ground truth)."""
    hint = q.get("answer_hint") or ""
    t = terms(hint)
    # Drop terms that are too generic to prove anything (short/common tokens already filtered by
    # dedup.terms' stoplist + len>2; this just keeps the check honest about what "evidence" means).
    return t


def snippet_evidence_ratio(snippet: str, needed: set[str]) -> tuple[int, int]:
    if not needed:
        return 0, 0
    hay = terms(snippet)
    hit = len(needed & hay)
    return hit, len(needed)


def locate_evidence_in_note(gw, source_file: str, needed: set[str]) -> dict:
    """Ground truth: which section of the FULL note actually contains the evidence terms."""
    try:
        text = gw.vault.read(source_file)
    except (OSError, PermissionError, ValueError) as e:
        return {"error": str(e)}
    best = None
    for sec in split_sections(text):
        hay = terms(sec.text)
        hit = len(needed & hay)
        if hit and (best is None or hit > best["hits"]):
            best = {"heading": sec.heading_path, "line": sec.line, "hits": hit, "of": len(needed)}
    return best or {"heading": None, "line": None, "hits": 0, "of": len(needed)}


def check_question(gw, rc, q: dict, path: str = "frozen", *, vault: Path | None = None,
                   use_cache: bool = True) -> dict:
    needed = evidence_terms(q)
    exp_sources = set(q.get("expected_sources") or [])
    vault = Path(vault) if vault is not None else Path(rc.vault_path)

    if path == "frozen":
        # Same candidate generation graphify_jev uses: allow_ppr=False (frozen pipeline, §5.5).
        uniq = cached_candidates(gw, vault, q["question"], use_cache=use_cache)
        judged_in, withheld, pf = prefilter(q["question"], uniq, rc.prefilter_top_k,
                                            rc.prefilter_lexical_weight)
        candidates_in, candidates_sent = pf["prefilter_in"], pf["prefilter_sent"]
    elif path == "opt":
        # Same free-stage cascade graphify_jev_opt runs, under the production default (§1.3):
        # candidates -> smart snippet (extract/fit_or_keep) -> ranking -> dedup -> adaptive-K.
        from app.retrieval.pipelines_opt import select_pool
        from config.optimization import OptimizationConfig
        fs = select_pool(gw, q["question"], DEFAULT_MAX_RESULTS,
                         opt=OptimizationConfig.default_cascade())
        judged_in, withheld = fs.pool, fs.withheld
        candidates_in = len(fs.pool) + len(fs.withheld)
        candidates_sent = len(fs.pool)
    else:
        raise ValueError(f"unknown --path {path!r}, expected 'frozen' or 'opt'")

    survivor = next((c for c in judged_in if c.source_file in exp_sources), None)
    withheld_hit = next((c for c in withheld if c.source_file in exp_sources), None)

    out = {
        "qid": q["id"],
        "path": path,
        "question": q["question"],
        "expected_sources": sorted(exp_sources),
        "prefilter_top_k": rc.prefilter_top_k,
        "candidates_in": candidates_in,
        "candidates_sent_to_jev": candidates_sent,
        "expected_source_reached_jev": survivor is not None,
    }

    if survivor is not None:
        hit, of = snippet_evidence_ratio(survivor.snippet, needed)
        out.update({
            # `section` is the candidate's ORIGINAL heading metadata (unchanged by smart-snippet,
            # it is sent to the judge as its own payload field regardless) — `snippet_strategy`
            # is what actually tells you whether the opt path re-cut the snippet text itself.
            "section_chosen": survivor.section,
            "snippet_strategy": (survivor.meta or {}).get("snippet_strategy"),
            "snippet_tokens": survivor.token_estimate or estimate_tokens(survivor.snippet),
            "snippet_contains_evidence": hit == of and of > 0,
            "snippet_evidence_terms_hit": f"{hit}/{of}",
        })
    elif withheld_hit is not None:
        out["note"] = "expected source retrieved but cut by the pre-filter before reaching JEV"
        out["withheld_section"] = withheld_hit.section
    else:
        out["note"] = "expected source not even among retrieval candidates"

    out["evidence_location_in_full_note"] = (
        locate_evidence_in_note(gw, sorted(exp_sources)[0], needed) if exp_sources else None
    )
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", required=True, help="path to the real benchmark/questions.json")
    ap.add_argument("--vault", required=True, help="path to the real (read-only) vault")
    ap.add_argument("--qids", nargs="*", default=list(DEFAULT_QIDS))
    ap.add_argument("--path", choices=("frozen", "opt", "both"), default="both",
                    help="frozen=dedup.preprocess (graphify_jev); opt=snippet.extract cascade "
                         "(graphify_jev_opt); both=run and report both (default)")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "jev_snippet_check.json"))
    ap.add_argument("--no-cache", action="store_true",
                    help="ignora o cache de candidatos e re-executa a recuperação")
    a = ap.parse_args()

    qs_all = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    targets = [q for q in qs_all if q["id"] in a.qids]

    vault = Path(a.vault).resolve()
    gw = make_gw(vault)
    rc = gw.retrieval_cfg

    paths = ("frozen", "opt") if a.path == "both" else (a.path,)
    results = [check_question(gw, rc, q, path=p, vault=vault, use_cache=not a.no_cache)
               for p in paths for q in targets]
    report = {"vault": str(vault), "questions_checked": a.qids, "paths": list(paths),
              "results": results}

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
