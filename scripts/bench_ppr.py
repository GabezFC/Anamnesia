"""Compare graphify retrieval with and without PPR expansion (§5.5, HippoRAG-style). No LLM calls.

Measures deterministic recall (overall and COMPLEX/multi-hop), total_tokens_spent and latency for
pipeline="graphify" with PPR_ENABLED off (BFS, current default) vs on, over the bundled synthetic
vault and, optionally, a real vault + question set passed via --vault-real/--real-questions.

A question counts as COMPLEX/multi-hop when its qclass is "multi_hop" (synthetic corpus) or it has
2+ expected_sources (works for both corpora; the real benchmark/questions.json has no qclass field).

Runs are NOT persisted (persist=False) and use a throwaway BenchmarkConfig.db_path in a tempdir, so
the real benchmark.db is never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("MEMORY_GATEWAY_VAULT", str(PROJECT_ROOT / "data" / "synthetic_vault"))

from config.benchmark import BenchmarkConfig  # noqa: E402
from config.optimizer import OptimizerConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.retrieval.graphify_hybrid import GraphIndex  # noqa: E402


def _ensure_fresh_graph(gw: MemoryGateway, vault: Path) -> None:
    """`warm()` swallows a failed `graphify update` (app/gateway/memory_gateway.py) so the gateway
    degrades gracefully in production instead of crashing. For a benchmark that is exactly the
    wrong behaviour: data/vault_mirror is SHARED across every make_gw() call in this script (the
    mirror path does not depend on which vault is loaded), so a swallowed failure silently leaves
    the PREVIOUS vault's graph.json in place and this script would compare two arms against the
    wrong graph without any error. Cheap guard: if the loaded graph's own source_file does not
    exist under the vault we asked for, force a real rebuild and reload.
    """
    gw.graph_index.load()
    sample = (gw.graph_index.nodes[0].get("source_file") if gw.graph_index.nodes else None)
    if sample and not (vault / str(sample).replace("\\", "/")).exists():
        gw.graphify.build(force=True)
        gw.graph_index.load()


def make_gw(vault: Path, ppr_enabled: bool) -> MemoryGateway:
    rc = RetrievalConfig(vault_path=vault)
    rc.ppr_enabled = ppr_enabled
    bc = BenchmarkConfig(db_path=str(Path(tempfile.mkdtemp()) / "b.db"), profile="benchmark")
    ocfg = OptimizerConfig.disabled()
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=ocfg)
    g = vault / "graphify-out" / "graph.json"
    if g.exists():
        gw.graph_index = GraphIndex(g)
    gw.warm()
    if not g.exists():
        _ensure_fresh_graph(gw, vault)
    return gw


def is_complex(q: dict) -> bool:
    return q.get("qclass") == "multi_hop" or len(q.get("expected_sources") or []) >= 2


def run_arm(gw, qs: list) -> dict:
    rows = []
    for q in qs:
        t0 = time.perf_counter()
        r = gw.search(q["question"], "graphify", 10, persist=False)
        lat = (time.perf_counter() - t0) * 1000
        files = [s.file for s in r.sources]
        exp = q.get("expected_sources") or []
        row = {
            "qid": q["id"], "answerable": q.get("answerable", True), "complex": is_complex(q),
            "lat": lat, "total_tokens_spent": r.metrics.get("total_tokens_spent", 0),
            "expand_mode": r.metrics.get("graphify_expand_mode"),
        }
        if row["answerable"] and exp:
            row["recall"] = sum(e in files for e in exp) / len(exp)
        rows.append(row)
    ans = [r for r in rows if "recall" in r]
    cpl = [r for r in ans if r["complex"]]
    return {
        "questions": len(rows),
        "answerable": len(ans),
        "recall_mean": round(statistics.mean(r["recall"] for r in ans), 4) if ans else None,
        "recall_full": sum(r["recall"] == 1.0 for r in ans),
        "complex_questions": len(cpl),
        "complex_recall_mean": round(statistics.mean(r["recall"] for r in cpl), 4) if cpl else None,
        "complex_recall_full": sum(r["recall"] == 1.0 for r in cpl),
        "total_tokens_spent_mean": round(statistics.mean(r["total_tokens_spent"] for r in rows), 1),
        "latency_ms_median": round(statistics.median(r["lat"] for r in rows), 1),
        "expand_modes_seen": sorted({r["expand_mode"] for r in rows if r["expand_mode"]}),
        "_rows": rows,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic-questions", default=str(PROJECT_ROOT / "benchmark" / "synthetic_questions.json"))
    ap.add_argument("--vault-synthetic", default=str(PROJECT_ROOT / "data" / "synthetic_vault"))
    ap.add_argument("--real-questions", default=None, help="path to the real benchmark/questions.json")
    ap.add_argument("--vault-real", default=None, help="path to the real (read-only) vault")
    ap.add_argument("--out", default=str(PROJECT_ROOT / "docs" / "ppr_bench.json"))
    ap.add_argument("--rows", action="store_true", help="keep per-question rows in the JSON output")
    a = ap.parse_args()

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "corpora": {}}

    qs_syn = json.loads(Path(a.synthetic_questions).read_text(encoding="utf-8"))
    vault_syn = Path(a.vault_synthetic).resolve()
    report["corpora"]["synthetic"] = {
        "bfs": run_arm(make_gw(vault_syn, False), qs_syn),
        "ppr": run_arm(make_gw(vault_syn, True), qs_syn),
    }

    if a.real_questions and a.vault_real:
        qs_real = json.loads(Path(a.real_questions).read_text(encoding="utf-8"))
        vault_real = Path(a.vault_real).resolve()
        report["corpora"]["real"] = {
            "bfs": run_arm(make_gw(vault_real, False), qs_real),
            "ppr": run_arm(make_gw(vault_real, True), qs_real),
        }

    if not a.rows:
        for corpus in report["corpora"].values():
            for arm in corpus.values():
                arm.pop("_rows", None)

    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
