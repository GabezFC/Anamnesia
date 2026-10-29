"""Measure the SQLite items of Onda 2 on a COPY of benchmark.db (never the real file).

  ana060  ms per save_run: legacy behaviour (commit per statement, synchronous=FULL) vs new (one
          transaction, synchronous=NORMAL), with ~24 candidates per run.
  ana103  EXPERIMENT dedicated async writer: p95 of save_run under N concurrent clients, flag off vs on.
  ana104  EXPERIMENT read-only reader connection: p95 of a dashboard-style read (`benchmark_rows`)
          while writers hammer the DB, flag off vs on.

  python scripts/experiments/measure_db_experiments.py [ana060 ana103 ana104] [--src benchmark.db] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics as st
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database.db import Database  # noqa: E402


def copy_db(src: Path, dst: Path) -> None:
    """Consistent copy via the online-backup API (read-only on the source)."""
    s = sqlite3.connect(f"file:{src.resolve().as_posix()}?mode=ro", uri=True)
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def pct(xs, p):
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))], 2) if s else None


def make_row(i: int, tag: str) -> tuple[dict, list[dict]]:
    row = {"run_id": f"m-{tag}-{i}", "session_id": f"measure-{tag}", "created_at": time.time(), "query": "q",
           "pipeline": "baseline", "context": "C" * 2200, "answer": None, "warmup": 0, "cache_enabled": 0,
           "metrics_json": json.dumps({"x": "y" * 3600}), "config_json": json.dumps({"k": 1}),
           "sources_json": "[]"}
    cands = [{"candidate_id": f"c{j}", "source_file": f"f{j}.md", "section": "s", "score": 0.5} for j in range(24)]
    return row, cands


def legacy_save(db: Database, row: dict, cands: list[dict]) -> None:
    """Pre-ANA-060 write path: one autocommit per statement."""
    row = dict(row)
    Database._fill_ledger_fields(row)
    row["config_hash"] = "h" + row["run_id"][-3:]
    row["config_json"] = None
    cols = ["run_id", "session_id", "created_at", "query", "pipeline", "context", "warmup", "cache_enabled",
            "metrics_json", "sources_json", "config_hash", "project", "cost_origin"]
    with db._lock:
        c = db.conn
        c.execute("INSERT OR IGNORE INTO configs (hash, json) VALUES (?,?)", (row["config_hash"], "{}"))
        c.commit()
        c.execute(f"INSERT OR REPLACE INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                  tuple(row.get(k) for k in cols))
        c.commit()
        for cd in cands:
            c.execute("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
                      (row["run_id"], cd["candidate_id"], cd["source_file"], cd["section"], cd["score"],
                       None, None, None, None))
            c.commit()


def ana060(src: Path, n: int = 150) -> dict:
    out = {}
    for label in ("legacy", "new"):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            p = Path(tmp) / "copy.db"
            copy_db(src, p)
            db = Database(p)
            if label == "legacy":
                db.conn.execute("PRAGMA synchronous=FULL")
            lat = []
            for i in range(n):
                row, cands = make_row(i, label)
                t = time.perf_counter()
                if label == "legacy":
                    legacy_save(db, row, cands)
                else:
                    db.save_run(row, cands)
                lat.append((time.perf_counter() - t) * 1000)
            out[label] = {"n": n, "mean_ms": round(st.mean(lat), 2), "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95)}
            db.close()
    out["speedup_mean"] = round(out["legacy"]["mean_ms"] / out["new"]["mean_ms"], 2)
    return out


def _hammer(db: Database, clients: int, per_client: int, tag: str):
    lat: list[float] = []
    errs: list[str] = []
    m = threading.Lock()

    def w(k):
        for i in range(per_client):
            row, cands = make_row(k * 100000 + i, tag)
            t = time.perf_counter()
            try:
                db.save_run(row, cands)
                d = (time.perf_counter() - t) * 1000
                with m:
                    lat.append(d)
            except Exception as e:  # noqa: BLE001
                with m:
                    errs.append(str(e))

    ts = [threading.Thread(target=w, args=(k,)) for k in range(clients)]
    t0 = time.perf_counter()
    [t.start() for t in ts]
    [t.join() for t in ts]
    db.flush()
    return lat, errs, time.perf_counter() - t0


def ana103(src: Path, clients: int = 8, per_client: int = 25, e2e_notes: int = 1000, e2e_requests: int = 96) -> dict:
    out = {}
    for label, flag in (("off", False), ("on", True)):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            p = Path(tmp) / "copy.db"
            copy_db(src, p)
            db = Database(p, async_writes=flag)
            lat, errs, wall = _hammer(db, clients, per_client, label)
            rows = db.query("SELECT COUNT(*) n FROM runs WHERE session_id=?", (f"measure-{label}",))[0]["n"]
            out[label] = {"clients": clients, "caller_p50_ms": pct(lat, 50), "caller_p95_ms": pct(lat, 95),
                          "errors": len(errs), "locked_errors": sum("locked" in e for e in errs),
                          "rows_persisted": rows, "expected_rows": clients * per_client,
                          "wall_s_until_durable": round(wall, 2)}
            db.close()
    out["note"] = ("caller_* only times the enqueue (not an honest basis); the verdict uses the end-to-end "
                   "/search p95 below (real MemoryGateway.search, baseline pipeline, caches off)")
    import os

    import load_search
    e2e = {}
    for label, flag in (("off", "0"), ("on", "1")):
        os.environ["ANAMNESIA_DB_ASYNC_WRITES"] = flag
        try:
            rep = load_search.run(e2e_notes, [clients], e2e_requests, persist=True)
        finally:
            os.environ.pop("ANAMNESIA_DB_ASYNC_WRITES", None)
        lv = rep["levels"][0]
        e2e[label] = {k: lv[k] for k in ("p50_ms", "p95_ms", "errors", "throughput_rps")}
    o, n = e2e["off"]["p95_ms"], e2e["on"]["p95_ms"]
    out["e2e_search"] = {"notes": e2e_notes, "clients": clients, "requests": e2e_requests, **e2e}
    out["p95_improvement_pct"] = round((o - n) / o * 100, 1) if o else None
    out["verdict_rule"] = "PROMOTE if e2e /search p95 improves >= 30% AND 0 locked errors AND no row lost; else HOLD"
    out["verdict"] = ("PROMOTE" if out["p95_improvement_pct"] is not None and out["p95_improvement_pct"] >= 30
                      and out["on"]["locked_errors"] == 0 and out["on"]["rows_persisted"] == out["on"]["expected_rows"]
                      and e2e["on"]["errors"] == 0 else "HOLD")
    return out


def ana104(src: Path, readers: int = 2, reads: int = 10, writers: int = 4) -> dict:
    out = {}
    for label, flag in (("off", False), ("on", True)):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            p = Path(tmp) / "copy.db"
            copy_db(src, p)
            db = Database(p, read_connection=flag)
            stop = threading.Event()

            def writer(k):
                i = 0
                while not stop.is_set():
                    row, cands = make_row(k * 1000000 + i, label)
                    try:
                        db.save_run(row, cands)
                    except Exception:  # noqa: BLE001
                        pass
                    i += 1

            wt = [threading.Thread(target=writer, args=(k,), daemon=True) for k in range(writers)]
            [t.start() for t in wt]
            time.sleep(0.2)
            lat: list[float] = []
            errs: list[str] = []
            m = threading.Lock()

            def reader():
                for _ in range(reads):
                    t = time.perf_counter()
                    try:
                        db.benchmark_rows(session_id="opt-20260927-142846")
                        d = (time.perf_counter() - t) * 1000
                        with m:
                            lat.append(d)
                    except Exception as e:  # noqa: BLE001
                        with m:
                            errs.append(str(e))

            rt = [threading.Thread(target=reader) for _ in range(readers)]
            [t.start() for t in rt]
            [t.join() for t in rt]
            stop.set()
            [t.join(timeout=5) for t in wt]
            out[label] = {"read_p50_ms": pct(lat, 50), "read_p95_ms": pct(lat, 95), "errors": len(errs)}
            db.close()
    o, n = out["off"]["read_p95_ms"], out["on"]["read_p95_ms"]
    out["p95_improvement_pct"] = round((o - n) / o * 100, 1) if o else None
    out["verdict_rule"] = "PROMOTE if read p95 improves >= 30% AND 0 errors; else HOLD"
    out["verdict"] = ("PROMOTE" if out["p95_improvement_pct"] is not None and out["p95_improvement_pct"] >= 30
                      and out["on"]["errors"] == 0 else "HOLD")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", nargs="*", default=["ana060", "ana103", "ana104"])
    ap.add_argument("--src", default=str(Path(__file__).resolve().parents[2] / "benchmark.db"))
    ap.add_argument("--json")
    a = ap.parse_args()
    src = Path(a.src)
    if not src.exists():
        print(f"fonte inexistente: {src}", file=sys.stderr)
        return 2
    fns = {"ana060": ana060, "ana103": ana103, "ana104": ana104}
    res = {k: fns[k](src) for k in a.which}
    print(json.dumps(res, indent=2))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
