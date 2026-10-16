"""ANAM-008: list/get/find_similar com N notas, catalogo desligado (antes) x ligado (depois).

Uso: .venv/Scripts/python.exe docs/bench/anam008_bench.py [N=3000]
"""
from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def timed(fn, reps):
    ts = []
    for _ in range(reps):
        t = time.perf_counter()
        r = fn()
        ts.append((time.perf_counter() - t) * 1000)
    return r, ts


def run(n: int, catalog: bool) -> dict:
    os.environ["MG_MEMORY_CATALOG"] = "1" if catalog else "0"
    from app.memory_store import lifecycle
    from app.memory_store.store import SavedContextStore
    from synth_notes import make_corpus
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "saved_context"
        corpus = make_corpus(root, n)
        st = SavedContextStore(root, rate_per_min=10**6)
        probe_id = corpus["ids"][n // 2]
        out = {}
        r, ts = timed(st.list, 5)
        out["list_cold_ms"], out["list_warm_ms"] = round(ts[0], 1), round(statistics.median(ts[1:]), 1)
        out["list_n"] = len(r)
        r, ts = timed(lambda: st.get(probe_id), 20)
        out["get_median_ms"] = round(statistics.median(ts), 2)
        g = corpus["dup_groups"][0]
        note = st.get(g[0])
        r, ts = timed(lambda: lifecycle.find_similar(st, note.title, note.content, note.project), 3)
        out["find_similar_first_ms"], out["find_similar_warm_ms"] = round(ts[0], 1), round(min(ts[1:]), 1)
        out["find_similar_hits"] = len(r)
        return out


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    which = sys.argv[2] if len(sys.argv) > 2 else "both"
    import json
    res = {}
    for name, flag in (("antes (MG_MEMORY_CATALOG=0)", False), ("depois (catalogo)", True)):
        if which == "before" and flag:
            continue
        res[name] = run(n, flag)
        print(name, json.dumps(res[name]), flush=True)
