"""Load / concurrency benchmark for /memory/search (ANA-059).

Builds a deterministic synthetic vault (default 10 000 notes) in a TEMP dir (never the real vault, never
the real benchmark.db), then drives `MemoryGateway.search` (pipeline `baseline`: no network, no paid
calls) with 1 / 4 / 16 concurrent clients and records per level:
  p50 / p95 / max latency (ms), throughput (req/s), errors, RSS (MB, peak sampled), and
  SQLite write-lock wait (total ms / max ms / acquires) measured on `Database._lock`.

Gate (regression): `--baseline FILE` compares p95 per client level against a saved report and exits 1 if
any level is worse than `--tolerance` (default 1.5x) or has errors. `--save FILE` writes the report.

  python scripts/load_search.py --notes 10000 --clients 1 4 16 --requests 64 --save out.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORDS = ("arquitetura decisao driver banco dados fastapi python sqlite cache indice latencia vault nota projeto "
         "memoria contexto recuperacao ranking grafo semente consulta tempo token custo limite servidor cliente "
         "migracao backup retencao pipeline benchmark metrica").split()


def build_vault(root: Path, n: int, seed: int = 7) -> list[str]:
    """n markdown notes, each with a unique rare token so queries have a well-defined answer."""
    rng = random.Random(seed)
    rare = []
    for i in range(n):
        d = root / f"area{i % 20:02d}"
        d.mkdir(parents=True, exist_ok=True)
        tok = f"zq{i:05d}x"
        rare.append(tok)
        body = " ".join(rng.choice(WORDS) for _ in range(120))
        (d / f"nota-{i:05d}.md").write_text(
            f"---\nid: {i}\ntitle: Nota {i} {tok}\narea: Area{i % 20}\ntype: nota\ntags: [{rng.choice(WORDS)}]\n"
            f"status: ativo\n---\n# Nota {i} {tok}\n\n{body}\n\n## Detalhes\n\n"
            f"{' '.join(rng.choice(WORDS) for _ in range(60))} {tok}\n", encoding="utf-8")
    return rare


def rss_mb() -> float:
    """Resident set size of this process in MB (psutil if present, else OS APIs; NaN if unavailable)."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1048576
    except Exception:  # noqa: BLE001
        pass
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            k32, ps = ctypes.windll.kernel32, ctypes.windll.psapi
            k32.GetCurrentProcess.restype = wintypes.HANDLE
            ps.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
            c = PMC()
            c.cb = ctypes.sizeof(c)
            if ps.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
                return c.WorkingSetSize / 1048576
        else:
            with open("/proc/self/statm") as f:
                return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576
    except Exception:  # noqa: BLE001
        pass
    return float("nan")


class LockProbe:
    """Wraps Database._lock to measure how long callers wait to acquire it."""

    def __init__(self, db):
        self._inner = db._lock
        self.waits_ms: list[float] = []
        self._m = threading.Lock()
        db._lock = self

    def __enter__(self):
        t = time.perf_counter()
        self._inner.acquire()
        w = (time.perf_counter() - t) * 1000
        with self._m:
            self.waits_ms.append(w)
        return self

    def __exit__(self, *a):
        self._inner.release()

    def acquire(self, *a, **k):
        return self._inner.acquire(*a, **k)

    def release(self):
        self._inner.release()

    def summary(self) -> dict:
        w = self.waits_ms
        return {"acquires": len(w), "total_ms": round(sum(w), 2), "max_ms": round(max(w), 2) if w else 0.0}


def pct(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 2) if s else float("nan")


def run_level(gw, queries: list[str], clients: int, requests: int, persist: bool, probe: LockProbe) -> dict:
    probe.waits_ms.clear()
    lat: list[float] = []
    errors: list[str] = []
    m = threading.Lock()
    todo = [queries[i % len(queries)] for i in range(requests)]
    idx = {"i": 0}
    peak = {"rss": rss_mb()}
    stop = threading.Event()

    def sampler():
        while not stop.wait(0.05):
            r = rss_mb()
            if r == r:
                peak["rss"] = max(peak["rss"], r)

    def worker():
        while True:
            with m:
                if idx["i"] >= len(todo):
                    return
                q = todo[idx["i"]]
                idx["i"] += 1
            t = time.perf_counter()
            try:
                gw.search(q, pipeline="baseline", max_results=10, persist=persist)
                d = (time.perf_counter() - t) * 1000
                with m:
                    lat.append(d)
            except Exception as e:  # noqa: BLE001
                with m:
                    errors.append(f"{type(e).__name__}: {e}")

    ts = [threading.Thread(target=worker) for _ in range(clients)]
    sp = threading.Thread(target=sampler, daemon=True)
    sp.start()
    t0 = time.perf_counter()
    [t.start() for t in ts]
    [t.join() for t in ts]
    wall = time.perf_counter() - t0
    stop.set()
    return {"clients": clients, "requests": requests, "ok": len(lat), "errors": len(errors),
            "error_samples": errors[:3], "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95),
            "max_ms": round(max(lat), 2) if lat else None, "mean_ms": round(st.mean(lat), 2) if lat else None,
            "throughput_rps": round(len(lat) / wall, 2) if wall else None,
            "rss_mb_peak": round(peak["rss"], 1), "lock_wait": probe.summary()}


def run(notes: int, clients: list[int], requests: int, persist: bool = True, workdir: Path | None = None) -> dict:
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig

    with tempfile.TemporaryDirectory(dir=workdir, ignore_cleanup_errors=True) as tmp:
        tmp_p = Path(tmp)
        vault = tmp_p / "vault"
        t = time.perf_counter()
        rare = build_vault(vault, notes)
        build_s = time.perf_counter() - t
        rc = RetrievalConfig(vault_path=vault, data_dir=tmp_p / "data")
        bc = BenchmarkConfig(db_path=str(tmp_p / "load.db"), profile="production", benchmark_mode=True)  # caches off: every request does real work
        gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc)
        t = time.perf_counter()
        gw.warm()
        warm_s = time.perf_counter() - t
        rng = random.Random(11)
        queries = [f"{rng.choice(WORDS)} {rare[rng.randrange(len(rare))]}" for _ in range(max(requests, 32))]
        probe = LockProbe(gw.db)
        levels = [run_level(gw, queries, c, requests, persist, probe) for c in clients]
        gw.db.close()
    return {"notes": notes, "build_s": round(build_s, 2), "warm_s": round(warm_s, 2), "persist": persist,
            "python": sys.version.split()[0], "cpu_count": os.cpu_count(), "levels": levels}


def gate(report: dict, baseline: dict, tolerance: float) -> list[str]:
    base = {lv["clients"]: lv for lv in baseline.get("levels", [])}
    bad = []
    for lv in report["levels"]:
        b = base.get(lv["clients"])
        if lv["errors"]:
            bad.append(f"{lv['clients']} clientes: {lv['errors']} erros")
        if b and b.get("p95_ms") and lv["p95_ms"] > b["p95_ms"] * tolerance:
            bad.append(f"{lv['clients']} clientes: p95 {lv['p95_ms']}ms > {tolerance}x baseline {b['p95_ms']}ms")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--notes", type=int, default=10000)
    ap.add_argument("--clients", type=int, nargs="+", default=[1, 4, 16])
    ap.add_argument("--requests", type=int, default=64)
    ap.add_argument("--no-persist", action="store_true")
    ap.add_argument("--save")
    ap.add_argument("--baseline")
    ap.add_argument("--tolerance", type=float, default=1.5)
    a = ap.parse_args()
    rep = run(a.notes, a.clients, a.requests, persist=not a.no_persist)
    print(json.dumps(rep, indent=2))
    if a.save:
        Path(a.save).write_text(json.dumps(rep, indent=2), encoding="utf-8")
    if a.baseline:
        bad = gate(rep, json.loads(Path(a.baseline).read_text(encoding="utf-8")), a.tolerance)
        for b in bad:
            print("GATE FALHOU:", b, file=sys.stderr)
        return 1 if bad else 0
    return 1 if any(lv["errors"] for lv in rep["levels"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
