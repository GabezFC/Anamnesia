"""ANA-102 EXPERIMENT: in-memory BaselineIndex.build() vs persistent IncrementalBaselineIndex.

Everything happens in a temp directory (synthetic vault + index file); no real vault/db is touched.

  python scripts/measure_incremental_index.py [--sizes 1000 5000 10000] [--changed-pct 1] [--repeat 3] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.retrieval.incremental_index import IncrementalBaselineIndex  # noqa: E402
from app.retrieval.baseline import BaselineIndex  # noqa: E402
from app.services.obsidian import ObsidianVault  # noqa: E402

WORDS = ("gateway cache fila banco deploy retencao billing runtime painel bucket pool memoria vetor grafo "
         "contexto agente juiz benchmark latencia custo token nota vault indice busca").split()


def make_vault(root: Path, n: int, seed: int = 7) -> None:
    rnd = random.Random(seed)
    for i in range(n):
        d = root / f"d{i % 50}"
        d.mkdir(parents=True, exist_ok=True)
        body = "\n\n".join(f"## Secao {j}\n\n" + " ".join(rnd.choice(WORDS) for _ in range(60)) for j in range(4))
        (d / f"n{i}.md").write_text(f"---\nstatus: ativo\n---\n# Nota {i}\n\n{body}\n", encoding="utf-8")


def timed(fn):
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def measure(n: int, changed_pct: float, repeat: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="ana102_", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        root = tmp / "vault"
        make_vault(root, n)
        vault = ObsidianVault(root)
        mem = [timed(BaselineIndex(vault).build) for _ in range(repeat)]
        db = tmp / "idx" / "index.db"
        first_idx = IncrementalBaselineIndex(vault, db)
        first = timed(first_idx.build)
        first_idx.close()
        warm, warm_stats = [], None
        for _ in range(repeat):
            inc = IncrementalBaselineIndex(vault, db)  # fresh object = new process
            warm.append(timed(inc.build))
            warm_stats = inc.last_stats
            inc.close()
        k = max(1, int(n * changed_pct / 100))
        files = vault.list_markdown()[:k]
        for rel in files:
            p = root / rel
            p.write_text(p.read_text(encoding="utf-8") + "\n\nalteracao zzquux\n", encoding="utf-8")
            os.utime(p, ns=(time.time_ns(), time.time_ns() + 1))
        inc = IncrementalBaselineIndex(vault, db)
        upd = timed(inc.build)
        upd_stats = inc.last_stats
        q_mem_idx = BaselineIndex(vault)
        q_mem_idx.build()
        qs = ["gateway cache", "deploy retencao", "zzquux", "benchmark latencia custo"]
        qm = [timed(lambda q=q: q_mem_idx.search(q)) for q in qs]
        qi = [timed(lambda q=q: inc.search(q)) for q in qs]
        same = all(sorted((c.source_file, c.section) for c in q_mem_idx.search(q))
                   == sorted((c.source_file, c.section) for c in inc.search(q)) for q in ("zzquux",))
        inc.close()
        q_mem_idx.conn.close()
        return {
            "notes": n, "changed_notes": k,
            "mem_build_ms_median": round(st.median(mem), 1),
            "inc_first_build_ms": round(first, 1),
            "inc_warm_build_ms_median": round(st.median(warm), 1), "inc_warm_stats": warm_stats,
            "inc_update_ms": round(upd, 1), "inc_update_stats": upd_stats,
            "search_ms_mem_mean": round(st.mean(qm), 2), "search_ms_inc_mean": round(st.mean(qi), 2),
            "zzquux_results_identical": same,
            "success_warm_lt_2s_at_10k": (st.median(warm) < 2000) if n >= 10000 else None,
            "warm_speedup_x": round(st.median(mem) / max(st.median(warm), 0.01), 2),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 5000, 10000])
    ap.add_argument("--changed-pct", type=float, default=1.0)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args()
    res = [measure(n, a.changed_pct, a.repeat) for n in a.sizes]
    for r in res:
        print(json.dumps(r, ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
