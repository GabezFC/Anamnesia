"""ANA-060 (single-transaction save_run + PRAGMAs), ANA-095 (retention at startup), ANA-099 (jev_cache
governance), ANA-103/104 (experiments: flags OFF by default, correct when ON)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import pytest

from app.database import retention
from app.database.db import Database
from app.services.jev_cache import CacheIdentity

DAY = 86400


def _row(run_id, age_days=0.0, **kw):
    r = {"run_id": run_id, "session_id": "s", "created_at": time.time() - age_days * DAY, "query": "q",
         "pipeline": "baseline", "context": "C" * 1000, "answer": "A", "sources_json": "[]",
         "metrics_json": json.dumps({"jev_cost": 0.1}), "config_json": {"k": 1}}
    r.update(kw)
    return r


def _cands(n=24):
    return [{"candidate_id": f"c{i}", "source_file": "f.md", "section": "s", "score": 0.5} for i in range(n)]


# ------------------------------------------------------------------ ANA-060
def test_pragmas_applied(tmp_path):
    d = Database(tmp_path / "t.db")
    assert d.query("PRAGMA busy_timeout")[0]["timeout"] == 5000
    assert d.query("PRAGMA synchronous")[0]["synchronous"] == 1          # NORMAL
    assert d.query("PRAGMA journal_mode")[0]["journal_mode"] == "wal"
    assert d.query("PRAGMA wal_autocheckpoint")[0]["wal_autocheckpoint"] == 1000


def test_save_run_is_one_commit(tmp_path):
    """Before: 1 commit for configs + 1 for runs + 24 for candidates (26 commits)."""
    d = Database(tmp_path / "t.db")
    commits = []
    d.conn.set_trace_callback(lambda s: commits.append(s) if s.strip().upper().startswith("COMMIT") else None)
    d.save_run(_row("r1"), _cands(24))
    assert len(commits) == 1
    assert d.query("SELECT COUNT(*) n FROM candidates WHERE run_id='r1'")[0]["n"] == 24
    assert d.get_run("r1")["config"] == {"k": 1}


def test_save_run_is_atomic_on_failure(tmp_path):
    d = Database(tmp_path / "t.db")
    with pytest.raises(KeyError):                                # bad candidate while building rows
        d.save_run(_row("r1"), _cands(3) + [{"candidate_id": "x"}])
    assert d.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 0
    assert d.query("SELECT COUNT(*) n FROM configs")[0]["n"] == 0
    # failure INSIDE the transaction (after config+run were inserted) rolls everything back too
    d.conn.execute("CREATE TRIGGER boom BEFORE INSERT ON candidates BEGIN SELECT RAISE(ABORT,'boom'); END")
    with pytest.raises(sqlite3.DatabaseError):
        d.save_run(_row("r2"), _cands(2))
    assert d.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 0
    assert d.query("SELECT COUNT(*) n FROM configs")[0]["n"] == 0
    d.conn.execute("DROP TRIGGER boom")
    d.save_run(_row("r3"), _cands(2))                            # lock released: still usable
    assert d.get_run("r3")


def test_concurrent_save_run_no_lock_errors(tmp_path):
    d = Database(tmp_path / "t.db")
    errs = []

    def w(k):
        try:
            for i in range(10):
                d.save_run(_row(f"r{k}-{i}"), _cands(5))
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=w, args=(k,)) for k in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    assert d.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 80
    assert d.query("SELECT COUNT(*) n FROM candidates")[0]["n"] == 400


def test_run_seq_still_notifies(tmp_path):
    d = Database(tmp_path / "t.db")
    s = d.run_seq
    d.save_run(_row("r1"))
    assert d.run_seq == s + 1


# ------------------------------------------------------------------ ANA-099
def _put(d, key, ident, age_days):
    d.conn.execute("INSERT INTO jev_cache VALUES (?,?,?)",
                   (key, json.dumps({"identity": ident, "relevance": 0.9}), time.time() - age_days * DAY))
    d.conn.commit()


def test_purge_stale_by_identity_ttl_and_cap(tmp_path):
    d = Database(tmp_path / "t.db")
    _put(d, "cur-new", "AAA", 1)
    _put(d, "cur-old", "AAA", 90)
    _put(d, "other", "BBB", 1)
    d.conn.execute("INSERT INTO jev_cache VALUES ('legacy','{}',?)", (time.time() - 1 * DAY,))   # no identity
    d.conn.commit()
    dry = d.purge_stale(current_identity="AAA", ttl_days=30, apply=False)
    assert dry["candidates"] == 2 and dry["deleted"] == 0 and d.cache_stats()["rows"] == 4
    r = d.purge_stale(current_identity="AAA", ttl_days=30)
    assert r["deleted"] == 2
    assert {x["key"] for x in d.query("SELECT key FROM jev_cache")} == {"cur-new", "legacy"}
    capped = d.purge_stale(max_rows=1)                           # keep the newest 1
    assert capped["deleted"] == 1 and d.cache_stats()["rows"] == 1


def test_cache_key_ignores_thresholds_but_not_other_components():
    """hit-rate is kept after moving a threshold: the cache stores raw scores, not decisions."""
    base = dict(model="m", prompt_version="p", jev_mode="performance", relevance_threshold=0.78,
                review_threshold=0.55)
    a = CacheIdentity(**base)
    assert CacheIdentity(**{**base, "relevance_threshold": 0.9}).digest() == a.digest()
    assert CacheIdentity(**{**base, "review_threshold": 0.4}).digest() == a.digest()
    assert CacheIdentity(**{**base, "model": "other"}).digest() != a.digest()
    assert CacheIdentity(**{**base, "prompt_version": "p2"}).digest() != a.digest()


def test_threshold_change_keeps_layered_hits():
    from app.services.jev_cache import LayeredCache
    store: dict = {}
    base = dict(model="m", prompt_version="p", jev_mode="performance")
    LayeredCache(store.get, store.__setitem__,
                 CacheIdentity(**base, relevance_threshold=0.78, review_threshold=0.55)
                 ).put_judgement("q driver", "h1", {"relevance": 0.9})
    other = LayeredCache(store.get, store.__setitem__,
                         CacheIdentity(**base, relevance_threshold=0.85, review_threshold=0.60))
    hit = other.get_judgement("q driver", "h1")[0]
    assert hit and hit["relevance"] == 0.9


# ------------------------------------------------------------------ ANA-095
def test_startup_retention_is_noop_by_default(tmp_path, monkeypatch):
    for k in ("ANAMNESIA_DB_RETENTION_DAYS", "ANAMNESIA_JEV_CACHE_TTL_DAYS", "ANAMNESIA_DB_VACUUM_DAYS"):
        monkeypatch.delenv(k, raising=False)
    d = Database(tmp_path / "t.db")
    d.save_run(_row("old", 100))
    assert retention.startup_maintenance(d) is None
    assert d.get_run("old")["context"] == "C" * 1000


def test_startup_retention_applies_when_enabled(tmp_path, monkeypatch):
    p = tmp_path / "t.db"
    d = Database(p)
    d.save_run(_row("old", 100))
    d.save_run(_row("new", 1))
    _put(d, "k_old", "A", 100)
    _put(d, "k_new", "A", 1)
    d.close()
    monkeypatch.setenv("ANAMNESIA_DB_RETENTION_DAYS", "30")
    monkeypatch.setenv("ANAMNESIA_DB_VACUUM_DAYS", "30")
    d2 = Database(p)                                             # retention fires at startup
    assert d2.get_run("old")["context"] is None and d2.get_run("old")["metrics"] == {"jev_cost": 0.1}
    assert d2.get_run("new")["context"] == "C" * 1000
    assert {r["key"] for r in d2.query("SELECT key FROM jev_cache")} == {"k_new"}
    assert d2.get_kv("last_vacuum")                              # monthly VACUUM recorded
    rep = retention.startup_maintenance(d2)
    assert not rep or "vacuumed" not in rep                      # not due again
    d2.close()


def test_size_alert_logs_warning(tmp_path, monkeypatch, caplog):
    d = Database(tmp_path / "t.db")
    monkeypatch.setenv("ANAMNESIA_DB_MAX_MB", "0.0001")
    with caplog.at_level("WARNING", logger="anamnesia.retention"):
        rep = retention.startup_maintenance(d)
    assert rep and "size_alert_mb" in rep and "ANAMNESIA_DB_MAX_MB" in caplog.text


def test_retention_failure_never_blocks_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "startup_maintenance", lambda db: 1 / 0)
    Database(tmp_path / "t.db").close()


def test_compress_old_contexts_roundtrip_and_dry_run(tmp_path):
    d = Database(tmp_path / "t.db")
    d.save_run(_row("old", 100, context="texto repetido " * 200))
    d.save_run(_row("new", 1, context="texto repetido " * 200))
    dry = retention.compress_old_contexts(d, 30)
    assert dry["rows"] == 1 and dry["bytes_after"] < dry["bytes_before"] and dry["compressed"] == 0
    assert d.query("SELECT context_encoding e FROM runs WHERE run_id='old'")[0]["e"] is None
    retention.compress_old_contexts(d, 30, apply=True)
    assert d.query("SELECT context_encoding e FROM runs WHERE run_id='old'")[0]["e"] == "zlib+b64"
    run = d.get_run("old")
    assert run and run["context"] == "texto repetido " * 200      # transparent on read
    assert d.query("SELECT context_encoding e FROM runs WHERE run_id='new'")[0]["e"] is None


def test_footprint_reports_columns(tmp_path):
    d = Database(tmp_path / "t.db")
    d.save_run(_row("r1"), _cands(4))
    f = retention.footprint(d)
    assert f["runs"] == 1 and f["bytes"]["runs.context"] == 1000 and f["mb_per_1000_runs"] > 0


# ------------------------------------------------------------------ ANA-103 / ANA-104 (experiments)
def test_experiment_flags_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ANAMNESIA_DB_ASYNC_WRITES", raising=False)
    monkeypatch.delenv("ANAMNESIA_DB_READER", raising=False)
    d = Database(tmp_path / "t.db")
    assert d._writer is None and d._reader is None
    d.save_run(_row("r1"))
    assert d.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 1          # synchronous path


def test_async_writer_persists_everything_and_reads_your_writes(tmp_path):
    d = Database(tmp_path / "t.db", async_writes=True)
    for i in range(30):
        d.save_run(_row(f"r{i}"), _cands(3))
    assert d.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 30          # query() flushes first
    assert d.query("SELECT COUNT(*) n FROM candidates")[0]["n"] == 90
    assert d._writer and not d._writer.errors
    d.close()


def test_async_writer_error_does_not_kill_thread(tmp_path):
    d = Database(tmp_path / "t.db", async_writes=True)
    d.save_run(_row("bad"), [{"candidate_id": "x"}])                    # KeyError inside the writer thread
    d.save_run(_row("good"))
    assert d.flush()
    assert d.get_run("good") and d.get_run("bad") is None
    assert d._writer and len(d._writer.errors) == 1
    d.close()


def test_async_writer_flag_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DB_ASYNC_WRITES", "1")
    d = Database(tmp_path / "t.db")
    assert d._writer is not None
    d.close()


def test_read_only_reader_sees_committed_rows_and_cannot_write(tmp_path):
    d = Database(tmp_path / "t.db", read_connection=True)
    assert d._reader is not None
    d.save_run(_row("r1"))
    assert d.query("SELECT COUNT(*) n FROM runs")[0]["n"] == 1          # served by the ro connection
    with pytest.raises(sqlite3.OperationalError):
        d._reader.execute("DELETE FROM runs")
    assert d.query("PRAGMA user_version")[0]["user_version"] >= 1       # non-SELECT goes to the main conn
    d.close()


def test_reader_concurrent_with_writers(tmp_path):
    d = Database(tmp_path / "t.db", read_connection=True)
    stop = threading.Event()
    errs = []

    def writer():
        i = 0
        while not stop.is_set():
            d.save_run(_row(f"w{i}"), _cands(2))
            i += 1

    t = threading.Thread(target=writer)
    t.start()
    try:
        for _ in range(50):
            try:
                d.query("SELECT COUNT(*) n FROM runs")
            except Exception as e:  # noqa: BLE001
                errs.append(e)
    finally:
        stop.set()
        t.join()
    assert not errs
    d.close()
