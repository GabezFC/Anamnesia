"""ANA-061/062/096/134: PRAGMA user_version + single migration runner, v0 -> current, idempotency,
refusal of future-version DBs, automatic backup before migrating. Always on tmp_path DBs."""
from __future__ import annotations

import sqlite3
import time

import pytest

from app.database.db import Database
from app.database.migrations import (
    ANAMNESIA_MIGRATIONS, BENCHMARK_MIGRATIONS, Migration, SchemaVersionError, current_version,
    latest_version, run_migrations)
from app.terminals.projects import ProjectRegistry

# The ORIGINAL pre-versioning schema (first shipped code: no migrated columns, redundant indexes).
V0_SCHEMA = """
CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at REAL, kind TEXT, config_json TEXT, notes TEXT);
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY, session_id TEXT, created_at REAL, question_id TEXT, query TEXT,
  pipeline TEXT, agent TEXT, provider TEXT, model TEXT, mode TEXT, repetition INTEGER,
  warmup INTEGER DEFAULT 0, order_index INTEGER, threshold REAL, jev_mode TEXT, jev_model TEXT,
  cache_enabled INTEGER, config_json TEXT, metrics_json TEXT, sources_json TEXT,
  context TEXT, answer TEXT, error TEXT);
CREATE INDEX runs_session ON runs(session_id);
CREATE INDEX runs_created ON runs(created_at);
CREATE TABLE candidates (run_id TEXT, candidate_id TEXT, source_file TEXT, section TEXT, score REAL,
  relevance REAL, injection REAL, decision TEXT, tokens INTEGER);
CREATE TABLE jev_cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL);
"""


def make_v0(path):
    c = sqlite3.connect(str(path))
    c.executescript(V0_SCHEMA)
    c.execute("INSERT INTO sessions VALUES ('s1', 1.0, 'search', '{}', '')")
    c.execute("INSERT INTO runs (run_id, session_id, created_at, query, pipeline, context, metrics_json)"
              " VALUES ('r1','s1',100.0,'q','baseline','CTX','{\"jev_cost\": 0.25}')")
    c.execute("INSERT INTO candidates VALUES ('r1','c1','f.md','s',0.5,0.9,0.0,'KEEP',10)")
    c.execute("INSERT INTO jev_cache VALUES ('k','{\"relevance\":0.9}',50.0)")
    c.commit()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    c.close()


def _names(db, typ):
    return {r["name"] for r in db.query(f"SELECT name FROM sqlite_master WHERE type='{typ}'")}


def test_fresh_db_gets_latest_user_version(tmp_path):
    d = Database(tmp_path / "n.db")
    assert current_version(d.conn) == latest_version(BENCHMARK_MIGRATIONS) >= 2
    assert d.migration_report["backup"] is None            # empty file: nothing to back up
    d.close()


def test_v0_database_migrates_preserving_data(tmp_path):
    p = tmp_path / "old.db"
    make_v0(p)
    d = Database(p)
    assert current_version(d.conn) == latest_version(BENCHMARK_MIGRATIONS)
    run = d.get_run("r1")
    assert run and run["context"] == "CTX" and run["metrics"] == {"jev_cost": 0.25}
    assert run["candidates"][0]["decision"] == "KEEP"
    assert d.cache_get("k") == {"relevance": 0.9}
    cols = {r["name"] for r in d.query("PRAGMA table_info(runs)")}
    assert {"config_hash", "context_encoding", "project", "routing_strategy"} <= cols   # columns added
    assert {"configs", "budgets", "kv", "routing_decisions"} <= _names(d, "table")      # tables added
    d.save_run({"run_id": "r2", "session_id": "s1", "created_at": time.time(), "query": "q2",
                "pipeline": "baseline"})                                                # fully usable
    assert d.get_run("r2")
    d.close()


def test_migration_is_idempotent(tmp_path):
    p = tmp_path / "old.db"
    make_v0(p)
    Database(p).close()
    d = Database(p)
    assert d.migration_report["applied"] == []             # nothing left to apply
    before = d.query("SELECT * FROM runs")
    assert run_migrations(d.conn, BENCHMARK_MIGRATIONS, path=p)["applied"] == []
    assert d.query("SELECT * FROM runs") == before
    d.close()


def test_baseline_migration_body_is_idempotent_even_if_rerun(tmp_path):
    """A half-migrated legacy DB (columns exist, version 0) must not blow up on re-application."""
    d = Database(tmp_path / "x.db")
    d.conn.execute("PRAGMA user_version=0")
    d.close()
    d2 = Database(tmp_path / "x.db")                        # re-applies migration 1 and 2 over existing objects
    assert current_version(d2.conn) == latest_version(BENCHMARK_MIGRATIONS)
    d2.close()


def test_future_version_is_refused_and_untouched(tmp_path):
    p = tmp_path / "future.db"
    make_v0(p)
    c = sqlite3.connect(str(p))
    c.execute(f"PRAGMA user_version={latest_version(BENCHMARK_MIGRATIONS) + 5}")
    c.commit()
    c.close()
    raw_before = p.read_bytes()
    with pytest.raises(SchemaVersionError, match="versão de schema"):
        Database(p)
    assert p.read_bytes() == raw_before                     # not altered (not even WAL mode/indexes)
    assert not list(tmp_path.glob("*.bak-v*"))              # and no pointless backup


def test_backup_created_before_migrating_existing_db(tmp_path):
    p = tmp_path / "benchmark.db"
    make_v0(p)
    d = Database(p)
    bak = d.migration_report["backup"]
    assert bak and bak.endswith("benchmark.db.bak-v0")
    c = sqlite3.connect(bak)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0                       # pre-migration snapshot
    assert c.execute("SELECT context FROM runs WHERE run_id='r1'").fetchone()[0] == "CTX"
    assert "kv" not in {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    c.close()
    d.close()
    Database(p).close()                                     # already current: no second backup
    assert len(list(tmp_path.glob("benchmark.db.bak-v*"))) == 1


def test_failed_migration_rolls_back_and_keeps_version(tmp_path):
    p = tmp_path / "f.db"
    c = sqlite3.connect(str(p), isolation_level=None)
    c.execute("CREATE TABLE t (a)")

    def good(cx):
        cx.execute("CREATE TABLE ok (a)")

    def bad(cx):
        cx.execute("CREATE TABLE half (a)")
        raise RuntimeError("boom")

    ms = (Migration(1, "good", good), Migration(2, "bad", bad))
    with pytest.raises(RuntimeError):
        run_migrations(c, ms, path=p, label="t")
    assert current_version(c) == 1                           # 1 applied, 2 rolled back entirely
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    assert "ok" in names and "half" not in names
    c.close()


def test_duplicate_or_zero_versions_rejected(tmp_path):
    c = sqlite3.connect(":memory:")
    with pytest.raises(ValueError):
        run_migrations(c, (Migration(1, "a", lambda x: None), Migration(1, "b", lambda x: None)))
    with pytest.raises(ValueError):
        run_migrations(c, (Migration(0, "a", lambda x: None),))


def test_redundant_indexes_dropped_and_not_recreated(tmp_path):
    """ANA-134: 16 -> 14 explicit/auto indexes; legacy files lose them, fresh files never get them."""
    p = tmp_path / "old.db"
    make_v0(p)
    legacy = sqlite3.connect(str(p))
    assert {"runs_session", "runs_created"} <= {r[0] for r in legacy.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    legacy.close()
    d = Database(p)
    idx = _names(d, "index")
    assert not ({"runs_session", "runs_created"} & idx)
    assert {"runs_session_created", "runs_created_at"} <= idx
    d.close()
    fresh = Database(tmp_path / "fresh.db")
    assert not ({"runs_session", "runs_created"} & _names(fresh, "index"))
    # the queries those indexes served still use an index (prefix of runs_session_created)
    plan = " ".join(str(tuple(r)) for r in fresh.conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM runs WHERE session_id='x'").fetchall())
    assert "USING INDEX" in plan.upper() or "USING COVERING INDEX" in plan.upper()
    fresh.close()


# ---- the second database (terminals `projects`) goes through the SAME runner -------------------
def test_projects_registry_uses_the_runner(tmp_path):
    p = tmp_path / "anamnesia.db"
    reg = ProjectRegistry(p)
    c = sqlite3.connect(str(p))
    assert c.execute("PRAGMA user_version").fetchone()[0] == latest_version(ANAMNESIA_MIGRATIONS)
    c.close()
    ProjectRegistry(p)                                       # reopen: idempotent
    assert reg.migration_report["label"] == "anamnesia.db"


def test_legacy_projects_db_migrates_with_backup_and_data(tmp_path):
    p = tmp_path / "anamnesia.db"
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL UNIQUE,"
              " created_at REAL NOT NULL)")
    c.execute("INSERT INTO projects VALUES ('p1','Proj','C:/x',1.0)")
    c.commit()
    c.close()
    reg = ProjectRegistry(p)
    assert reg.migration_report["backup"].endswith("anamnesia.db.bak-v0")
    c = sqlite3.connect(str(p))
    assert c.execute("SELECT name FROM projects WHERE id='p1'").fetchone()[0] == "Proj"
    c.close()


def test_projects_future_version_refused(tmp_path):
    p = tmp_path / "anamnesia.db"
    c = sqlite3.connect(str(p))
    c.execute("PRAGMA user_version=99")
    c.commit()
    c.close()
    with pytest.raises(SchemaVersionError):
        ProjectRegistry(p)
