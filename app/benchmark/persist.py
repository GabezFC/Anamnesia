"""Benchmark persistence helpers: isolation from the production ledger (ANA-089) and cache
declaration guard (ANA-091).

* ANA-089 — one SQLite file PER benchmark session (``bench_sessions/<session>.db`` next to the
  production ``benchmark.db``); the production file stays production-only. Analysis across files uses
  ``ATTACH`` (``attach_for_analysis``). ``production_benchmark_runs`` measures the success metric
  (benchmark runs in the production ledger = 0).
* ANA-091 — a comparison session recorded with ``cache_enabled=1`` must be explicitly declared
  (``allow_cache``); otherwise the run is refused. ``undeclared_cache_sessions`` audits a DB for the
  success metric (0 comparison sessions with cache on and no declaration).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from app.database.db import Database

# session kinds that are benchmark/comparison material (not interactive/adhoc traffic)
BENCHMARK_KINDS = ("retrieval", "end_to_end", "opt_benchmark", "benchmark", "threshold_sweep", "routing")


class CacheNotDeclaredError(RuntimeError):
    """A benchmark was about to be recorded with caches ON without an explicit declaration."""


def _safe(session_id: str) -> str:
    s = re.sub(r"\.{2,}", "_", re.sub(r"[^A-Za-z0-9._-]+", "_", session_id)).strip("._")
    if not s:
        raise ValueError("session_id vazio/ inválido")
    return s[:120]


def bench_db_path(session_id: str, production_db: str | Path) -> Path:
    """``<dir of production db>/bench_sessions/<session>.db`` — never the production file itself."""
    p = Path(production_db).parent / "bench_sessions" / f"{_safe(session_id)}.db"
    if p.resolve() == Path(production_db).resolve():  # pragma: no cover - defensive
        raise ValueError("o BENCH_DB não pode ser o banco de produção")
    return p


def open_bench_db(session_id: str, production_db: str | Path, **kw) -> Database:
    return Database(bench_db_path(session_id, production_db), **kw)


def attach_for_analysis(conn: sqlite3.Connection, bench_db: str | Path, alias: str = "bench") -> str:
    """ATTACH a per-session file read-only for cross-file analysis; returns the alias."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
        raise ValueError("alias inválido")
    uri = Path(bench_db).resolve().as_uri() + "?mode=ro"
    conn.execute(f"ATTACH DATABASE ? AS {alias}", (uri,))
    return alias


def production_benchmark_runs(db: Database) -> int:
    """Runs in `db` that belong to benchmark-kind sessions (ANA-089 metric; target 0 when isolated)."""
    marks = ",".join("?" * len(BENCHMARK_KINDS))
    return db.query(f"SELECT COUNT(*) n FROM runs r JOIN sessions s ON s.session_id=r.session_id"
                    f" WHERE s.kind IN ({marks})", BENCHMARK_KINDS)[0]["n"]


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


def require_cache_declared(cache_enabled: bool, allow_cache: bool, namespace: str = "") -> dict:
    """Fail unless caches are off or the caller declared ``allow_cache``. Returns the declaration to
    store in the session config (so reports can show it and audits can find it)."""
    if cache_enabled and not allow_cache:
        raise CacheNotDeclaredError(
            "cache ligado em sessão de benchmark sem declaração: use BENCHMARK_MODE=true (caches off) "
            "ou passe --allow-cache para registrar a comparação como 'com cache'.")
    return {"cache_enabled": bool(cache_enabled), "allow_cache": bool(allow_cache),
            "cache_namespace": namespace or ""}


def undeclared_cache_sessions(db: Database) -> list[dict]:
    """Benchmark-kind sessions with runs cache_enabled=1 whose config lacks ``allow_cache: true``."""
    marks = ",".join("?" * len(BENCHMARK_KINDS))
    rows = db.query(
        f"SELECT s.session_id, s.kind, s.config_json, SUM(r.cache_enabled=1) AS cached_runs, COUNT(*) AS runs"
        f" FROM sessions s JOIN runs r ON r.session_id=s.session_id WHERE s.kind IN ({marks})"
        f" GROUP BY s.session_id HAVING cached_runs > 0", BENCHMARK_KINDS)
    out = []
    for r in rows:
        try:
            cfg = json.loads(r["config_json"] or "{}")
        except ValueError:
            cfg = {}
        if not (isinstance(cfg, dict) and cfg.get("allow_cache") is True):
            out.append({"session_id": r["session_id"], "kind": r["kind"], "cached_runs": r["cached_runs"],
                        "runs": r["runs"]})
    return out
