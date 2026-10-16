"""ANAM-006: retenção/expurgo de runs (cascata sem órfãos, backup, hash do contexto, migração aditiva)."""
import hashlib
import shutil
import time

import pytest

from app.cli.main import build_parser, cmd_db_prune
from app.database.db import Database

DAY = 86400
CHILD = ("candidates", "routing_decisions", "verification_results", "evaluations",
         "false_negatives", "retrieval_labels")


def _seed(db, rid, age_days, session="s", context="CTX secreto"):
    db.save_run({"run_id": rid, "session_id": session, "created_at": time.time() - age_days * DAY,
                 "query": "pergunta", "pipeline": "p", "context": context, "answer": "resposta",
                 "metrics_json": {}, "config_json": {}},
                [{"candidate_id": "c1", "source_file": "a.md", "section": "s", "score": 1.0}])
    for sql in (
        "INSERT INTO routing_decisions (run_id) VALUES (?)",
        "INSERT INTO verification_results (run_id, attempt) VALUES (?, 1)",
        "INSERT INTO evaluations (run_id, accuracy) VALUES (?, 3)",
        "INSERT INTO false_negatives (run_id) VALUES (?)",
        "INSERT INTO retrieval_labels (run_id, label) VALUES (?, 'relevant_found')"):
        db._exec(sql, (rid,))


def _count(db, t, rid):
    return db.query(f"SELECT COUNT(*) n FROM {t} WHERE run_id=?", (rid,))[0]["n"]


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "b.db"))
    yield d
    d.conn.close()


def test_migration_adds_column_and_index(db):
    cols = {r["name"] for r in db.query("PRAGMA table_info(runs)")}
    assert "context_sha256" in cols
    idx = {r["name"] for r in db.query("PRAGMA index_list(candidates)")}
    assert "idx_candidates_source_file" in idx
    assert db.schema_version() >= 4


def test_migration_is_additive_on_v3_db(tmp_path):
    p = str(tmp_path / "old.db")
    d = Database(p)
    _seed(d, "r1", 1)
    d.conn.execute("DROP INDEX idx_candidates_source_file")
    d.conn.execute("ALTER TABLE runs DROP COLUMN context_sha256")
    d.conn.execute("PRAGMA user_version=3")
    d.conn.commit()
    d.conn.close()
    d2 = Database(p)
    assert d2.get_run("r1")["answer"] == "resposta"          # dados preservados
    assert "context_sha256" in {r["name"] for r in d2.query("PRAGMA table_info(runs)")}
    assert list(tmp_path.glob("old.db.bak-v3*"))               # backup automático da migração
    d2.conn.close()


def test_context_sha256_persisted(db):
    _seed(db, "r1", 0, context="abc")
    assert db.get_run("r1")["context_sha256"] == hashlib.sha256(b"abc").hexdigest()


def test_context_sha256_with_compression_and_metrics_only(tmp_path, monkeypatch):
    d = Database(str(tmp_path / "c.db"), compress_context=True)
    _seed(d, "r1", 0, context="x" * 500)
    assert d.get_run("r1")["context_sha256"] == hashlib.sha256(b"x" * 500).hexdigest()
    monkeypatch.setenv("ANAMNESIA_METRICS_ONLY", "1")
    _seed(d, "r2", 0, context="zzz")
    r = d.get_run("r2")
    assert r["context"] is None and r["context_sha256"] == hashlib.sha256(b"zzz").hexdigest()
    d.conn.close()


def test_prune_cascades_without_orphans(db):
    _seed(db, "old", 40)
    _seed(db, "new", 1)
    res = db.prune(30)
    assert res["deleted"] == 1
    for t in CHILD:
        assert _count(db, t, "old") == 0, t
        assert _count(db, t, "new") == 1, t
        orphans = db.query(f"SELECT COUNT(*) n FROM {t} WHERE run_id NOT IN (SELECT run_id FROM runs)")[0]["n"]
        assert orphans == 0, t


def test_prune_dry_run_changes_nothing(db):
    _seed(db, "old", 40)
    assert db.prune(30, dry_run=True)["would_delete"] == 1
    assert _count(db, "routing_decisions", "old") == 1


def test_purge_text_keeps_hash_and_row(db):
    _seed(db, "old", 40, context="segredo")
    _seed(db, "new", 1, context="recente")
    assert db.purge_run_text(30, dry_run=True)["would_purge"] == 1
    assert db.get_run("old")["answer"] == "resposta"
    assert db.purge_run_text(30)["purged"] == 1
    old = db.get_run("old")
    assert old["query"] is None and old["answer"] is None and old["context"] is None
    assert old["context_sha256"] == hashlib.sha256("segredo".encode()).hexdigest()
    assert db.get_run("new")["answer"] == "resposta"


def test_purge_text_backfills_hash_for_legacy_rows(db):
    _seed(db, "old", 40, context="legado")
    db._exec("UPDATE runs SET context_sha256=NULL")
    db.purge_run_text(30)
    assert db.get_run("old")["context_sha256"] == hashlib.sha256(b"legado").hexdigest()


def test_retention_env_default_and_override(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_RUNS_TEXT_RETENTION_DAYS", raising=False)
    assert Database.runs_text_retention_days() == 30
    monkeypatch.setenv("ANAMNESIA_RUNS_TEXT_RETENTION_DAYS", "7")
    assert Database.runs_text_retention_days() == 7
    monkeypatch.setenv("ANAMNESIA_RUNS_TEXT_RETENTION_DAYS", "lixo")
    assert Database.runs_text_retention_days() == 30


def _patch_cfg(monkeypatch, db_path):
    import config.benchmark as bm
    real = bm.BenchmarkConfig
    monkeypatch.setattr(bm, "BenchmarkConfig", lambda: real(db_path=db_path, profile="production"))


class _A:
    keep_days = 30
    keep_sessions = None
    dry_run = False
    vacuum = False
    yes = True
    purge_text = None


def test_cli_backup_then_rollback_restores(tmp_path, monkeypatch, capsys):
    p = str(tmp_path / "b.db")
    d = Database(p)
    _seed(d, "old", 40)
    _seed(d, "new", 1)
    d.conn.close()
    _patch_cfg(monkeypatch, p)
    cmd_db_prune(_A())
    out = capsys.readouterr().out
    baks = list(tmp_path.glob("b.db.bak-v*"))
    assert baks and '"backup"' in out
    d = Database(p)
    assert d.get_run("old") is None
    d.conn.close()
    # rollback: restaurar do .bak
    for ext in ("-wal", "-shm"):
        (tmp_path / f"b.db{ext}").unlink(missing_ok=True)
    shutil.copyfile(baks[0], p)
    d = Database(p)
    assert d.get_run("old") is not None and _count(d, "evaluations", "old") == 1
    d.conn.close()


def test_cli_dry_run_no_backup_no_delete(tmp_path, monkeypatch, capsys):
    p = str(tmp_path / "b.db")
    d = Database(p)
    _seed(d, "old", 40)
    d.conn.close()
    _patch_cfg(monkeypatch, p)
    a = _A()
    a.dry_run = True
    cmd_db_prune(a)
    assert '"would_delete": 1' in capsys.readouterr().out
    assert not list(tmp_path.glob("b.db.bak-v*"))
    d = Database(p)
    assert d.get_run("old") is not None
    d.conn.close()


def test_cli_without_yes_aborts_when_not_confirmed(tmp_path, monkeypatch, capsys):
    p = str(tmp_path / "b.db")
    d = Database(p)
    _seed(d, "old", 40)
    d.conn.close()
    _patch_cfg(monkeypatch, p)
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    a = _A()
    a.yes = False
    cmd_db_prune(a)
    assert '"aborted": true' in capsys.readouterr().out
    assert not list(tmp_path.glob("b.db.bak-v*"))
    d = Database(p)
    assert d.get_run("old") is not None
    d.conn.close()


def test_cli_parser_flags():
    a = build_parser().parse_args(["db-prune", "--keep-days", "30", "--yes", "--purge-text"])
    assert a.yes is True and a.purge_text == -1
    a = build_parser().parse_args(["db-prune", "--keep-days", "30", "--purge-text", "7"])
    assert a.purge_text == 7 and a.yes is False
