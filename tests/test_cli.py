"""CLI argument parsing (§7). No gateway, no vault: only argparse wiring is under test here."""
from __future__ import annotations

import time

import pytest

from app.cli.main import build_parser, cmd_db_prune
from app.schemas.models import PIPELINES


def test_search_pipeline_accepts_every_pipeline_plus_auto():
    p = build_parser()
    for pipeline in ("auto", *PIPELINES):
        a = p.parse_args(["search", "pergunta", "--pipeline", pipeline])
        assert a.pipeline == pipeline
    a = p.parse_args(["search", "pergunta"])
    assert a.pipeline == "auto"  # MOL stays the default (§1)


def test_benchmark_pipeline_accepts_every_pipeline_including_the_cascade():
    p = build_parser()
    a = p.parse_args(["benchmark", "--pipeline", "graphify_jev_opt"])
    assert a.pipeline == ["graphify_jev_opt"]
    for pipeline in PIPELINES:
        p.parse_args(["benchmark", "--pipeline", pipeline])  # must not raise


# -- db-prune (§5.3) ---------------------------------------------------------------
def test_db_prune_requires_keep_days():
    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["db-prune"])


def test_db_prune_parses_all_flags():
    p = build_parser()
    a = p.parse_args(["db-prune", "--keep-days", "30", "--keep-sessions", "a,b", "--dry-run", "--vacuum"])
    assert a.keep_days == 30
    assert a.keep_sessions == "a,b"
    assert a.dry_run is True
    assert a.vacuum is True


def test_db_prune_default_executes_not_dry_run():
    p = build_parser()
    a = p.parse_args(["db-prune", "--keep-days", "7"])
    assert a.dry_run is False
    assert a.vacuum is False
    assert a.keep_sessions is None


def test_cmd_db_prune_runs_end_to_end(tmp_path, monkeypatch, capsys):
    from app.database.db import Database
    import config.benchmark as benchmark_config

    db_path = str(tmp_path / "b.db")
    db = Database(db_path)
    now = time.time()
    db.save_run({"run_id": "old", "session_id": "s-old", "created_at": now - 40 * 86400,
                "query": "q", "pipeline": "baseline", "metrics_json": {}, "config_json": {}})
    db.save_run({"run_id": "kept", "session_id": "keep-me", "created_at": now - 40 * 86400,
                "query": "q", "pipeline": "baseline", "metrics_json": {}, "config_json": {}})
    db.conn.close()

    real_cfg_cls = benchmark_config.BenchmarkConfig
    monkeypatch.setattr(benchmark_config, "BenchmarkConfig",
                        lambda: real_cfg_cls(db_path=db_path, profile="production"))

    class Args:
        keep_days = 30
        keep_sessions = "keep-me"
        dry_run = False
        vacuum = True

    cmd_db_prune(Args())
    out = capsys.readouterr().out
    assert '"deleted": 1' in out
    assert '"vacuumed": true' in out

    db2 = Database(db_path)
    remaining = {r["run_id"] for r in db2.list_runs(limit=100)}
    assert remaining == {"kept"}
    db2.conn.close()
