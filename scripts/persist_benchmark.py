"""Persist one benchmark round per pipeline so the dashboard reflects the CURRENT code.

Validation during development ran with persist=False, so benchmark.db only held pre-optimisation
runs and the dashboard kept showing the old numbers. This writes a real, labelled session.

Usage:  python scripts/persist_benchmark.py [--session opt-2026-09-27] [--pipelines ...]
                                            [--allow-cache] [--isolate]

ANA-091: refuses to record a comparison with caches ON unless --allow-cache declares it.
ANA-089: --isolate (or ANAMNESIA_BENCH_ISOLATE=1) writes to bench_sessions/<session>.db instead of
         the production benchmark.db.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.benchmark.persist import (  # noqa: E402
    CacheNotDeclaredError, config_hash, open_bench_db, require_cache_declared)
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=f"opt-{time.strftime('%Y%m%d-%H%M%S')}")
    ap.add_argument("--pipelines", nargs="*", default=["baseline", "graphify", "graphify_jev"])
    ap.add_argument("--allow-cache", action="store_true", help="declara que a comparação roda com cache ligado")
    ap.add_argument("--isolate", action="store_true", help="grava em bench_sessions/<session>.db (ANA-089)")
    a = ap.parse_args()

    gw = MemoryGateway(db=None) if not (a.isolate or os.environ.get("ANAMNESIA_BENCH_ISOLATE") == "1") else None
    if gw is None:
        from config.benchmark import BenchmarkConfig
        bc = BenchmarkConfig()
        gw = MemoryGateway(bench_cfg=bc, db=open_bench_db(a.session, bc.db_path,
                                                          compress_context=bc.db_compress_context))
    try:
        decl = require_cache_declared(gw.bench_cfg.cache_enabled, a.allow_cache, gw.cache_namespace)
    except CacheNotDeclaredError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        raise SystemExit(2) from None
    cfg = {"pipelines": a.pipelines, **decl}
    cfg["config_hash"] = config_hash(cfg)
    gw.db.create_session(a.session, "benchmark", cfg, "persist_benchmark.py")
    print(f"cache: enabled={decl['cache_enabled']} allow_cache={decl['allow_cache']} "
          f"namespace={decl['cache_namespace']!r} config_hash={cfg['config_hash']}")
    gw.jev = gw.make_jev(gw.jev_cfg, cache=False)
    gw.warm()
    qs = [q for q in json.loads(Path("benchmark/questions.json").read_text(encoding="utf-8"))
          if q.get("answerable")]

    print(f"session: {a.session}   perguntas: {len(qs)}\n")
    for p in a.pipelines:
        hits = empty = 0
        ctx, tot, lat = [], [], []
        for q in qs:
            r = gw.search(q["question"], pipeline=p, max_results=10, persist=True,
                          run_meta={"session_id": a.session, "kind": "benchmark",
                                    "question_id": q["id"], "mode": "retrieval"})
            m = r.metrics
            hits += bool(set(q["expected_sources"]) & {s.file for s in r.sources})
            empty += m["context_tokens"] == 0
            ctx.append(m["context_tokens"])
            tot.append(m["total_tokens_spent"])
            lat.append(m["total_latency_ms"])
        print(f"  {p:<15} recall={hits}/{len(qs)}  ctx_med={st.median(ctx):,.0f}  "
              f"total_med={st.median(tot):,.0f}  lat_med={st.median(lat):,.0f}ms  vazios={empty}")

    print(f"\ngravado em benchmark.db (session_id={a.session})")


if __name__ == "__main__":
    main()
