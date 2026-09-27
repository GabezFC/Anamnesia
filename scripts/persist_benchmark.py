"""Persist one benchmark round per pipeline so the dashboard reflects the CURRENT code.

Validation during development ran with persist=False, so benchmark.db only held pre-optimisation
runs and the dashboard kept showing the old numbers. This writes a real, labelled session.

Usage:  python scripts/persist_benchmark.py [--session opt-2026-09-27] [--pipelines ...]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.gateway.memory_gateway import MemoryGateway  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default=f"opt-{time.strftime('%Y%m%d-%H%M%S')}")
    ap.add_argument("--pipelines", nargs="*", default=["baseline", "graphify", "graphify_jev"])
    a = ap.parse_args()

    gw = MemoryGateway()
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
