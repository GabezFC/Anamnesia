"""Deterministic sweep of PREFILTER_TOP_K / PREFILTER_LEXICAL_WEIGHT (§5.5 item 3). No LLM calls.

"Recall" here means: does a candidate from an expected_sources file survive the pre-filter cut
(i.e. would reach JEV), for every (K, lexical_weight) combination in the proposal's sweep grid.
Candidate generation (BM25 + graph expansion, allow_ppr=False to match the frozen graphify_jev
pipeline) runs ONCE per question with full snippets already attached; only the cheap prefilter
ranking varies per grid point, so the whole sweep costs zero extra retrieval calls.

Grid: K in {4,6,8,10,12,16,20}, lexical_weight in {0.0,0.15,0.3,0.5,0.7}. Current defaults (see
config/retrieval.py) are K=8, weight=0.3.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from itertools import product
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("MEMORY_GATEWAY_VAULT", str(PROJECT_ROOT / "data" / "synthetic_vault"))

from config.benchmark import BenchmarkConfig  # noqa: E402
from config.optimizer import OptimizerConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.retrieval.graphify_hybrid import GraphIndex  # noqa: E402
from app.retrieval.pipelines import _graphify_candidates  # noqa: E402
from app.services.prefilter import prefilter  # noqa: E402

KS = [4, 6, 8, 10, 12, 16, 20]
WS = [0.0, 0.15, 0.3, 0.5, 0.7]


def _ensure_fresh_graph(gw: MemoryGateway, vault: Path) -> None:
    """Guard against a stale data/vault_mirror graph from a previous vault (see scripts/bench_ppr.py
    for the full explanation: `warm()` swallows a failed `graphify update`, and the mirror path is
    shared across vaults, so a silent failure would otherwise sweep candidates built from the WRONG
    vault's graph without any error).
    """
    gw.graph_index.load()
    sample = (gw.graph_index.nodes[0].get("source_file") if gw.graph_index.nodes else None)
    if sample and not (vault / str(sample).replace("\\", "/")).exists():
        gw.graphify.build(force=True)
        gw.graph_index.load()


def make_gw(vault: Path) -> MemoryGateway:
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


def build_cache(gw, qs: list) -> dict:
    """Run candidate generation once per answerable question with expected_sources."""
    cache = {}
    for q in qs:
        if not q.get("answerable", True):
            continue
        exp = set(q.get("expected_sources") or [])
        if not exp:
            continue
        uniq, _metrics = _graphify_candidates(gw, q["question"], allow_ppr=False)
        cache[q["id"]] = (q["question"], uniq, exp)
    return cache


def sweep_corpus(cache: dict) -> list[dict]:
    rows = []
    for K, W in product(KS, WS):
        ratios = []
        full = 0
        for _qid, (query, uniq, exp) in cache.items():
            judged_in, _withheld, _pf = prefilter(query, uniq, K, W)
            survived = {c.source_file for c in judged_in} & exp
            ratio = len(survived) / len(exp)
            ratios.append(ratio)
            full += ratio == 1.0
        rows.append({
            "K": K, "W": W,
            "questions": len(ratios),
            "recall_mean": round(sum(ratios) / len(ratios), 4) if ratios else None,
            "recall_full": full,
        })
    return rows


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic-questions", default=str(PROJECT_ROOT / "benchmark" / "synthetic_questions.json"))
    ap.add_argument("--vault-synthetic", default=str(PROJECT_ROOT / "data" / "synthetic_vault"))
    ap.add_argument("--real-questions", default=None)
    ap.add_argument("--vault-real", default=None)
    ap.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "prefilter_sweep.json"))
    a = ap.parse_args()

    report = {}

    qs_syn = json.loads(Path(a.synthetic_questions).read_text(encoding="utf-8"))
    gw_syn = make_gw(Path(a.vault_synthetic).resolve())
    cache_syn = build_cache(gw_syn, qs_syn)
    report["synthetic"] = {"questions_with_expected_sources": len(cache_syn), "sweep": sweep_corpus(cache_syn)}

    if a.real_questions and a.vault_real:
        qs_real = json.loads(Path(a.real_questions).read_text(encoding="utf-8"))
        gw_real = make_gw(Path(a.vault_real).resolve())
        cache_real = build_cache(gw_real, qs_real)
        report["real"] = {"questions_with_expected_sources": len(cache_real), "sweep": sweep_corpus(cache_real)}

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
