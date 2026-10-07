"""Measure JEV/result cache hit rate, cold vs warm, on a tmp copy of the synthetic vault (pend. 3).

Replays N queries twice through MemoryGateway.search (pipeline graphify_jev, production profile =
caches ON) with a deterministic STUB JEV backend (no network, no paid tokens). Pass 1 (cold) fills the
caches; pass 2 (warm) replays the same queries. Reports, per pass: the optimizer result-cache stats,
JEV per-candidate cache hits/misses summed from run metrics, and stub backend calls.

WHAT THIS MEASURES: that the cache MECHANISM works (a repeated identical query hits; the second pass
spends 0 backend calls). It does NOT measure the real-world repetition rate of a user's queries: warm
hit rate ~100% here is by construction, because the same list is replayed. The real rate needs the
production `runs.metrics_json` (`result_cache_hit`, `jev_cache_hits`) over real usage.

    python scripts/measure_cache_hit_rate.py [--queries 8] [--vault PATH] [--json out.json]

Everything runs in a tmp dir; benchmark.db is never opened.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from config.benchmark import BenchmarkConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402

DISCLAIMER = ("Mede a correção do mecanismo de cache (consulta repetida idêntica -> hit; 2ª passada = 0 chamadas "
              "ao backend). NÃO mede a taxa real de repetição de consultas de um usuário; o hit rate 'warm' "
              "é ~100% por construção.")


class StubBackend:
    """Deterministic JEV stand-in: scores every question 0.9, fixed usage. Counts calls."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        return {k: 0.9 for k in questions}, {"input_tokens": 400, "output_tokens": 5}, "stub-jev"


def load_queries(n: int) -> list[str]:
    qf = ROOT / "benchmark" / "synthetic_questions.json"
    qs = [q["question"] for q in json.loads(qf.read_text(encoding="utf-8")) if q.get("answerable", True)]
    return qs[:n]


def run_pass(gw, backend, queries, pipeline="graphify_jev") -> dict:
    calls0 = backend.calls
    h0, m0 = gw.optimizer.cache.hits, gw.optimizer.cache.misses
    jh = jr = 0
    for q in queries:
        r = gw.search(q, pipeline, 5, persist=False)
        jd = r.metrics.get("jev") or {}
        jh += int(r.metrics.get("jev_cache_hits") or 0)
        jr += int(jd.get("candidates_received") or 0)
    hits, misses = gw.optimizer.cache.hits - h0, gw.optimizer.cache.misses - m0
    tot = hits + misses
    return {"result_cache": {"hits": hits, "misses": misses, "hit_rate": round(hits / tot, 4) if tot else None},
            "jev_candidate_cache": {"hits": jh, "candidates_received": jr,
                                    "hit_rate": round(jh / jr, 4) if jr else None},
            "jev_backend_calls": backend.calls - calls0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=8)
    ap.add_argument("--vault", default=str(ROOT / "data" / "synthetic_vault"))
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="cache_rate_"))
    try:
        vault = tmp / "vault"
        shutil.copytree(a.vault, vault)
        backend = StubBackend()
        rc = RetrievalConfig(vault_path=vault, data_dir=tmp / "data")
        bc = BenchmarkConfig(db_path=str(tmp / "m.db"), profile="production", benchmark_mode=False)
        gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, jev_backend=backend)
        gw.warm()
        graph = vault / "graphify-out" / "graph.json"
        if graph.exists():
            from app.retrieval.graphify_hybrid import GraphIndex
            gw.graph_index = GraphIndex(graph)
        queries = load_queries(a.queries)
        out = {"n_queries": len(queries), "stub_backend": True, "vault": "synthetic (tmp copy)",
               "cache_enabled": bc.cache_enabled, "cold": run_pass(gw, backend, queries),
               "warm": run_pass(gw, backend, queries),
               "free_pipeline_result_cache": {"cold": run_pass(gw, backend, queries, "auto"),
                                              "warm": run_pass(gw, backend, queries, "auto")},
               "notes": "Paid (JEV) pipelines are cached per candidate by the JEV cache; free pipelines "
                        "(auto->baseline) by the optimizer ResultCache (paid results are deliberately not "
                        "result-cached, see optimizer.cache_key).",
               "disclaimer": DISCLAIMER}
        print(json.dumps(out, indent=2, ensure_ascii=False))
        if a.json:
            Path(a.json).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            gw.db.conn.close()
        except Exception:  # noqa: BLE001
            pass
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
