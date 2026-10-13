"""Single schema-migration runner for every Anamnesia SQLite file (ANA-061, ANA-096, ANA-134).

One runner, several ordered migration lists (one list per database file):
  * BENCHMARK_MIGRATIONS  -> benchmark.db  (runs, candidates, jev_cache, configs, ledger, routing ...)
  * ANAMNESIA_MIGRATIONS  -> anamnesia.db  (terminals `projects` registry)

State lives in ``PRAGMA user_version`` (an integer in the SQLite header): the highest migration
already applied. Rules:
  * a database whose version is HIGHER than this code knows is refused (``SchemaVersionError``),
    untouched — downgrading silently would corrupt data written by a newer release;
  * before the first pending migration of an EXISTING database (has tables) a consistent copy is
    written next to it (``<file>.bak-v<from>``, ANA-096) using the sqlite online-backup API;
  * each migration runs in its own ``BEGIN IMMEDIATE`` transaction together with the version bump,
    so a crash leaves the previous version intact; the version is re-checked inside the lock so two
    processes opening the same file cannot apply a migration twice;
  * migration bodies must be idempotent (a v0 database may be in ANY historical shape: the legacy
    code created tables/columns lazily, never recording a version).

Migrations must not call ``executescript`` / ``commit`` (they would break the transaction): use
``run_script`` (splits on statement boundaries) or ``conn.execute``.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

log = logging.getLogger("anamnesia.migrations")


class SchemaVersionError(RuntimeError):
    """The database was written by a newer schema than this code understands."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def run_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a multi-statement script WITHOUT the implicit COMMIT of ``executescript``."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                conn.execute(buf)
            buf = ""
    if buf.strip():
        conn.execute(buf)


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def latest_version(migrations: Sequence[Migration]) -> int:
    return max((m.version for m in migrations), default=0)


def _has_user_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
                        ).fetchone() is not None


def backup_database(conn: sqlite3.Connection, path: str | Path, from_version: int) -> Path:
    """Consistent copy of the live database -> ``<path>.bak-v<from_version>`` (never overwrites)."""
    src = Path(path)
    dst = src.with_name(f"{src.name}.bak-v{from_version}")
    if dst.exists():
        dst = src.with_name(f"{src.name}.bak-v{from_version}-{time.strftime('%Y%m%d-%H%M%S')}")
    out = sqlite3.connect(str(dst))
    try:
        conn.backup(out)
    finally:
        out.close()
    return dst


def run_migrations(conn: sqlite3.Connection, migrations: Sequence[Migration], *,
                   path: str | Path | None = None, label: str = "db", backup: bool = True) -> dict:
    """Bring ``conn`` to the latest version. Returns a report (from/to/applied/backup)."""
    ordered = sorted(migrations, key=lambda m: m.version)
    versions = [m.version for m in ordered]
    if len(set(versions)) != len(versions) or (versions and versions[0] < 1):
        raise ValueError(f"{label}: migration versions must be unique integers >= 1")
    latest = latest_version(ordered)
    start = current_version(conn)
    report: dict = {"label": label, "from_version": start, "to_version": start, "latest": latest,
                    "applied": [], "backup": None}
    if start > latest:
        raise SchemaVersionError(
            f"{label}: o banco está na versão de schema {start}, mas este código só conhece até a {latest}. "
            f"Atualize o Anamnesia (ou restaure um backup '.bak-v*') — o arquivo não foi alterado.")
    pending = [m for m in ordered if m.version > start]
    if not pending:
        return report
    is_file = path is not None and str(path) not in ("", ":memory:") and Path(path).exists()
    if backup and is_file and _has_user_tables(conn):
        if conn.in_transaction:
            conn.commit()
        report["backup"] = str(backup_database(conn, path, start))  # type: ignore[arg-type]
        log.info("%s: backup antes de migrar v%s -> %s", label, start, report["backup"])
    for m in pending:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if current_version(conn) >= m.version:      # another process migrated meanwhile
                conn.rollback()
                continue
            m.apply(conn)
            conn.execute(f"PRAGMA user_version={int(m.version)}")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        report["applied"].append(f"{m.version}:{m.name}")
        report["to_version"] = m.version
        log.info("%s: migração %s aplicada", label, report["applied"][-1])
    report["to_version"] = current_version(conn)
    return report


# -- benchmark.db ---------------------------------------------------------------------------------
def _m1_baseline(conn: sqlite3.Connection) -> None:
    """Idempotent bootstrap: every table/column/index the pre-versioning code created lazily."""
    from app.database import db as _db
    run_script(conn, _db.SCHEMA)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    for col, decl in _db.RUNS_MIGRATED_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {decl}")
    # indexes on migrated columns can only be created after the ALTERs above
    conn.execute("CREATE INDEX IF NOT EXISTS runs_project_created ON runs(project, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS runs_created_at ON runs(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS runs_routing_strategy ON runs(routing_strategy)")


def _m2_drop_redundant_indexes(conn: sqlite3.Connection) -> None:
    """ANA-134: runs_created == runs_created_at; runs_session is a prefix of runs_session_created."""
    conn.execute("DROP INDEX IF EXISTS runs_created")
    conn.execute("DROP INDEX IF EXISTS runs_session")


def _m3_backfill_cost_origin(conn: sqlite3.Connection) -> None:
    """ANA-188: fill NULL cost_origin/project of old runs (batched, logged for rollback, idempotent)."""
    from app.services.cost_ledger import migration_apply
    migration_apply(conn)


BENCHMARK_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "baseline_schema", _m1_baseline),
    Migration(2, "drop_redundant_indexes", _m2_drop_redundant_indexes),
    Migration(3, "backfill_cost_origin", _m3_backfill_cost_origin),
)


# -- anamnesia.db (terminals) ---------------------------------------------------------------------
def _a1_projects(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                 " path TEXT NOT NULL UNIQUE, created_at REAL NOT NULL)")


ANAMNESIA_MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "projects_registry", _a1_projects),
)
