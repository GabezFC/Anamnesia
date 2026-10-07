"""T0.4: opt-in retention for benchmark.db (always on synthetic tmp_path DBs)."""
import json
import time

import pytest

from app.cli.main import build_parser, cmd_db_maintenance
from app.database.db import Database

DAY = 86400


def _row(run_id, age_days):
    return {"run_id": run_id, "session_id": "s1", "created_at": time.time() - age_days * DAY,
            "query": "q", "pipeline": "p", "context": "C" * 1000, "answer": "A" * 500,
            "sources_json": json.dumps([{"file": "x"}]), "metrics_json": json.dumps({"jev_cost": 0.5})}


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    d.save_run(_row("old", 100), candidates=[{"candidate_id": "c1", "source_file": "f", "section": "s", "score": 0.1}])
    d.save_run(_row("new", 1))
    d.conn.execute("INSERT INTO jev_cache VALUES ('k_old','{}',?)", (time.time() - 100 * DAY,))
    d.conn.execute("INSERT INTO jev_cache VALUES ('k_new','{}',?)", (time.time(),))
    d.conn.execute("INSERT INTO candidates (run_id, candidate_id) VALUES ('ghost','g1')")
    d.conn.commit()
    return d


def _snap(d):
    return (d.query("SELECT * FROM runs ORDER BY run_id"), d.query("SELECT * FROM jev_cache ORDER BY key"),
            d.query("SELECT * FROM candidates ORDER BY run_id, candidate_id"))


def test_dry_run_changes_nothing(db):
    before = _snap(db)
    r = db.maintenance(30)
    assert r["dry_run"] is True and r["found"]["runs_heavy_rows"] == 1
    assert r["found"]["jev_cache_rows"] == 1 and r["found"]["orphan_candidates"] == 1
    assert r["found"]["runs_heavy_bytes"] > 1500
    assert _snap(db) == before


def test_vacuum_ignored_without_apply(db):
    assert db.maintenance(30, apply=False, vacuum=True)["vacuumed"] is False


def test_apply_strips_only_old_heavy_columns(db):
    old_before = db.query("SELECT * FROM runs WHERE run_id='old'")[0]
    new_before = db.query("SELECT * FROM runs WHERE run_id='new'")[0]
    r = db.maintenance(30, apply=True)
    assert r["applied"] == {"runs_stripped": 1, "jev_cache_deleted": 1, "orphan_candidates_deleted": 1}
    old = db.query("SELECT * FROM runs WHERE run_id='old'")[0]
    assert old["context"] is None and old["answer"] is None and old["sources_json"] is None
    assert old["metrics_json"] == old_before["metrics_json"]
    for k in ("run_id", "session_id", "created_at", "query", "pipeline"):
        assert old[k] == old_before[k]
    assert db.query("SELECT * FROM runs WHERE run_id='new'")[0] == new_before
    assert db.get_run("old")["metrics"] == {"jev_cost": 0.5}
    assert [x["key"] for x in db.query("SELECT key FROM jev_cache")] == ["k_new"]
    assert [x["run_id"] for x in db.query("SELECT run_id FROM candidates")] == ["old"]


def test_apply_is_idempotent(db):
    db.maintenance(30, apply=True)
    snap = _snap(db)
    r = db.maintenance(30, apply=True)
    assert r["applied"] == {"runs_stripped": 0, "jev_cache_deleted": 0, "orphan_candidates_deleted": 0}
    assert _snap(db) == snap


def test_apply_with_vacuum(db):
    assert db.maintenance(30, apply=True, vacuum=True)["vacuumed"] is True


def test_negative_days_rejected(db):
    with pytest.raises(ValueError):
        db.maintenance(-1)


def test_cli_defaults_to_dry_run(db, capsys):
    a = build_parser().parse_args(["db-maintenance", "--db", db.path, "--older-than-days", "30"])
    assert a.apply is False
    before = _snap(db)
    cmd_db_maintenance(a)
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "file before" in out
    assert _snap(db) == before
    a = build_parser().parse_args(["db-maintenance", "--db", db.path, "--older-than-days", "30", "--apply"])
    cmd_db_maintenance(a)
    assert "APPLY" in capsys.readouterr().out
    assert db.query("SELECT context FROM runs WHERE run_id='old'")[0]["context"] is None
