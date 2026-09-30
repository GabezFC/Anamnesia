"""app/database/db.py: indices, config dedup, context compression, pagination/filters, prune (§5.3)."""
from __future__ import annotations

import time

import pytest

from app.database.db import Database


def _row(run_id, **over):
    base = {
        "run_id": run_id, "session_id": over.pop("session_id", "s1"), "created_at": time.time(),
        "question_id": None, "query": "pergunta de teste", "pipeline": "baseline",
        "agent": "mcp", "provider": None, "model": None, "mode": "retrieval", "repetition": 0,
        "warmup": 0, "order_index": None, "threshold": None, "jev_mode": None, "jev_model": None,
        "cache_enabled": 0, "config_json": {"jev": {"model": "x"}, "retrieval": {"a": "1"}},
        "metrics_json": {"context_tokens": 10, "client": None}, "sources_json": [],
        "context": "contexto de teste", "answer": None, "error": None,
    }
    base.update(over)
    return base


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "b.db"))
    yield d
    d.conn.close()


# -- indices ---------------------------------------------------------------------
@pytest.mark.parametrize("sql", [
    "SELECT * FROM runs WHERE created_at > 0",
    "SELECT * FROM runs WHERE pipeline='baseline' AND warmup=0",
    "SELECT * FROM candidates WHERE run_id='x'",
])
def test_indices_used_by_query_plan(db, sql):
    plan = db.query(f"EXPLAIN QUERY PLAN {sql}")
    text = " ".join(row.get("detail", "") for row in plan)
    assert "SCAN" not in text.upper() or "SEARCH" in text.upper(), text
    assert "USING INDEX" in text.upper() or "USING COVERING INDEX" in text.upper(), text


def test_indices_created_idempotently(tmp_path):
    path = str(tmp_path / "b.db")
    d1 = Database(path)
    d1.conn.close()
    d2 = Database(path)  # re-opening must not fail on CREATE INDEX IF NOT EXISTS / ALTER TABLE
    names = {r["name"] for r in d2.query("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"runs_created", "runs_pipeline_warmup", "cand_run", "runs_session"} <= names
    d2.conn.close()


# -- config dedup ------------------------------------------------------------------
def test_config_json_deduplicated_by_hash(db):
    db.save_run(_row("r1"))
    db.save_run(_row("r2"))  # identical config_json
    configs = db.query("SELECT COUNT(*) n FROM configs")[0]["n"]
    assert configs == 1
    raw = db.query("SELECT config_json, config_hash FROM runs WHERE run_id='r1'")[0]
    assert raw["config_json"] is None
    assert raw["config_hash"]


def test_get_run_resolves_config_through_hash(db):
    db.save_run(_row("r1"))
    run = db.get_run("r1")
    assert run["config"] == {"jev": {"model": "x"}, "retrieval": {"a": "1"}}


def test_list_runs_full_resolves_config_too(db):
    db.save_run(_row("r1"))
    rows = db.list_runs(full=True)
    assert rows[0]["config"] == {"jev": {"model": "x"}, "retrieval": {"a": "1"}}


def test_old_row_with_inline_config_json_still_reads(db):
    """Retrocompatibility: a row written before the dedup migration has config_json inline and no
    config_hash. _decode must still resolve it (never assume config_hash is set)."""
    db._exec(
        "INSERT INTO runs (run_id, session_id, created_at, query, pipeline, config_json, metrics_json)"
        " VALUES (?,?,?,?,?,?,?)",
        ("old1", "s1", time.time(), "q antiga", "baseline", '{"legacy": true}', '{"context_tokens": 1}'),
    )
    run = db.get_run("old1")
    assert run["config"] == {"legacy": True}


# -- context compression -----------------------------------------------------------
def test_context_plain_by_default(db):
    db.save_run(_row("r1"))
    raw = db.query("SELECT context, context_encoding FROM runs WHERE run_id='r1'")[0]
    assert raw["context"] == "contexto de teste"
    assert not raw["context_encoding"]
    assert db.get_run("r1")["context"] == "contexto de teste"


def test_context_compressed_round_trips(tmp_path):
    d = Database(str(tmp_path / "b.db"), compress_context=True)
    d.save_run(_row("r1"))
    raw = d.query("SELECT context, context_encoding FROM runs WHERE run_id='r1'")[0]
    assert raw["context_encoding"] == "zlib+b64"
    assert raw["context"] != "contexto de teste"
    assert d.get_run("r1")["context"] == "contexto de teste"
    d.conn.close()


def test_old_row_with_plain_context_reads_unchanged_when_compression_enabled(tmp_path):
    """Retrocompatibility: turning compression ON must not break rows written before the flag
    existed (context_encoding is NULL for those)."""
    d = Database(str(tmp_path / "b.db"), compress_context=True)
    d._exec(
        "INSERT INTO runs (run_id, session_id, created_at, query, pipeline, context, context_encoding)"
        " VALUES (?,?,?,?,?,?,?)",
        ("old1", "s1", time.time(), "q antiga", "baseline", "texto simples antigo", None),
    )
    assert d.get_run("old1")["context"] == "texto simples antigo"
    d.conn.close()


# -- pagination / filters ----------------------------------------------------------
def test_list_runs_pagination(db):
    for i in range(5):
        db.save_run(_row(f"r{i}", created_at=1000.0 + i))
    page1 = db.list_runs(limit=2, offset=0)
    page2 = db.list_runs(limit=2, offset=2)
    assert [r["run_id"] for r in page1] == ["r4", "r3"]
    assert [r["run_id"] for r in page2] == ["r2", "r1"]
    assert db.count_runs() == 5


def test_list_runs_filters_agent_session_q_since(db):
    db.save_run(_row("r1", agent="mcp", session_id="adhoc", query="sobre gatos", created_at=100.0))
    db.save_run(_row("r2", agent="rest", session_id="bench1", query="sobre cachorros", created_at=200.0))
    assert [r["run_id"] for r in db.list_runs(agent="mcp")] == ["r1"]
    assert [r["run_id"] for r in db.list_runs(session_id="bench1")] == ["r2"]
    assert [r["run_id"] for r in db.list_runs(q="gatos")] == ["r1"]
    assert [r["run_id"] for r in db.list_runs(since=150.0)] == ["r2"]
    assert db.count_runs(agent="mcp") == 1


def test_list_runs_adhoc_only(db):
    db.save_run(_row("r1", session_id="adhoc"))
    db.save_run(_row("r2", session_id="bench1"))
    assert [r["run_id"] for r in db.list_runs(adhoc_only=True)] == ["r1"]


def test_list_runs_query_is_preserved_literally(db):
    """§4/§5.1: the literal question text must round-trip untouched."""
    literal = "  Qual é   a decisão  sobre stack?  "
    db.save_run(_row("r1", query=literal.strip()))
    assert db.list_runs()[0]["query"] == literal.strip()
    assert db.get_run("r1")["query"] == literal.strip()


def test_list_runs_default_excludes_context_and_config(db):
    db.save_run(_row("r1"))
    lean = db.list_runs()[0]
    assert "context" not in lean and "config" not in lean and "sources" not in lean
    full = db.list_runs(full=True)[0]
    assert full["context"] == "contexto de teste"
    assert full["config"] == {"jev": {"model": "x"}, "retrieval": {"a": "1"}}


# -- legacy rewrite (maintenance pass on a pre-migration database) ---------------
def test_rewrite_legacy_rows_dedups_inline_config_json(db):
    for rid in ("old1", "old2"):
        db._exec(
            "INSERT INTO runs (run_id, session_id, created_at, query, pipeline, config_json, metrics_json)"
            " VALUES (?,?,?,?,?,?,?)",
            (rid, "s1", time.time(), "q", "baseline", '{"legacy": true}', "{}"),
        )
    result = db.rewrite_legacy_rows()
    assert result["configs_deduped"] == 2
    assert db.query("SELECT COUNT(*) n FROM configs")[0]["n"] == 1
    for rid in ("old1", "old2"):
        raw = db.query("SELECT config_json, config_hash FROM runs WHERE run_id=?", (rid,))[0]
        assert raw["config_json"] is None and raw["config_hash"]
        assert db.get_run(rid)["config"] == {"legacy": True}


def test_rewrite_legacy_rows_is_idempotent(db):
    db._exec(
        "INSERT INTO runs (run_id, session_id, created_at, query, pipeline, config_json, metrics_json)"
        " VALUES (?,?,?,?,?,?,?)",
        ("old1", "s1", time.time(), "q", "baseline", '{"legacy": true}', "{}"),
    )
    first = db.rewrite_legacy_rows(compress_context=True)
    second = db.rewrite_legacy_rows(compress_context=True)
    assert first["configs_deduped"] == 1
    assert second == {"configs_deduped": 0, "context_compressed": 0}


def test_rewrite_legacy_rows_can_compress_context(db):
    db._exec(
        "INSERT INTO runs (run_id, session_id, created_at, query, pipeline, context, metrics_json)"
        " VALUES (?,?,?,?,?,?,?)",
        ("old1", "s1", time.time(), "q", "baseline", "texto antigo bem grande" * 10, "{}"),
    )
    result = db.rewrite_legacy_rows(compress_context=True)
    assert result["context_compressed"] == 1
    raw = db.query("SELECT context, context_encoding FROM runs WHERE run_id='old1'")[0]
    assert raw["context_encoding"] == "zlib+b64"
    assert db.get_run("old1")["context"] == "texto antigo bem grande" * 10


def test_rewrite_legacy_rows_without_compress_leaves_context_untouched(db):
    db._exec(
        "INSERT INTO runs (run_id, session_id, created_at, query, pipeline, context, metrics_json)"
        " VALUES (?,?,?,?,?,?,?)",
        ("old1", "s1", time.time(), "q", "baseline", "texto antigo", "{}"),
    )
    db.rewrite_legacy_rows(compress_context=False)
    raw = db.query("SELECT context, context_encoding FROM runs WHERE run_id='old1'")[0]
    assert raw["context"] == "texto antigo"
    assert raw["context_encoding"] is None


# -- prune / vacuum -----------------------------------------------------------------
def test_prune_keeps_recent_and_protected_sessions(db):
    now = time.time()
    db.save_run(_row("old", session_id="s-old", created_at=now - 40 * 86400))
    db.save_run(_row("old-protected", session_id="keep-me", created_at=now - 40 * 86400))
    db.save_run(_row("recent", session_id="s-new", created_at=now))
    result = db.prune(keep_days=30, keep_sessions=["keep-me"])
    assert result == {"deleted": 1, "cutoff": pytest.approx(now - 30 * 86400, abs=1), "dry_run": False}
    remaining = {r["run_id"] for r in db.list_runs(limit=100)}
    assert remaining == {"old-protected", "recent"}
    assert db.query("SELECT COUNT(*) n FROM candidates WHERE run_id='old'")[0]["n"] == 0


def test_prune_dry_run_deletes_nothing(db):
    now = time.time()
    db.save_run(_row("old", created_at=now - 40 * 86400))
    result = db.prune(keep_days=30, dry_run=True)
    assert result == {"would_delete": 1, "cutoff": pytest.approx(now - 30 * 86400, abs=1), "dry_run": True}
    assert db.count_runs() == 1


def test_vacuum_does_not_raise(db):
    db.save_run(_row("r1"))
    db.vacuum()  # just must not raise; size effects are measured manually (see PR notes)
