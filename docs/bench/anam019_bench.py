"""ANAM-019: p50/p95 de MemoryGateway.search() (pipeline baseline, persist=True, jsonl ativo).

Uso: python docs/bench/anam019_bench.py <N> <rotulo>   (ANAMNESIA_GATEWAY_ASYNC_PERSIST=0|1 escolhe o modo)
Vault sintetico em diretorio temporario; ANAMNESIA_HOME isolado. Nao toca o vault real nem o benchmark.db real.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
home = tempfile.mkdtemp(prefix="anam019-")
os.environ["ANAMNESIA_HOME"] = home
sys.path.insert(0, str(ROOT))

from config.benchmark import BenchmarkConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402


def make_vault(root: Path, n: int = 60) -> None:
    for i in range(n):
        p = root / f"nota{i:03d}.md"
        body = "\n".join(f"Linha {j} sobre decisao {i} arquitetura python fastapi sqlite memoria contexto" for j in range(40))
        p.write_text(f"---\nid: {i}\ntitle: Nota {i}\n---\n# Nota {i}\n\n{body}\n", encoding="utf-8")


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    label = sys.argv[2] if len(sys.argv) > 2 else "run"
    vault = Path(home) / "vault"
    vault.mkdir()
    make_vault(vault)
    rcfg = RetrievalConfig(vault_path=vault, data_dir=Path(home) / "data")
    bcfg = BenchmarkConfig(db_path=str(Path(home) / "b.db"), profile="benchmark")
    gw = MemoryGateway(retrieval_cfg=rcfg, bench_cfg=bcfg)
    gw.warm()
    qs = [f"decisao {i % 50} arquitetura python" for i in range(n)]
    for q in qs[:10]:
        gw.search(q, "baseline", 5)
    lat = []
    for q in qs:
        t = time.perf_counter()
        gw.search(q, "baseline", 5)
        lat.append((time.perf_counter() - t) * 1000)
    t = time.perf_counter()
    gw.close() if hasattr(gw, "close") else None
    drain_ms = (time.perf_counter() - t) * 1000
    lat.sort()
    rows = gw.db.query("SELECT COUNT(*) c FROM runs")[0]["c"]
    out = {"label": label, "async": os.environ.get("ANAMNESIA_GATEWAY_ASYNC_PERSIST", "(default)"), "n": n,
           "p50_ms": round(statistics.median(lat), 2), "p95_ms": round(lat[int(0.95 * len(lat)) - 1], 2),
           "mean_ms": round(statistics.fmean(lat), 2), "drain_ms": round(drain_ms, 1), "runs_in_db": rows}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
