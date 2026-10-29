"""Synthetic regressions for index freshness and corpus/config identities."""
import os
import sqlite3
from types import SimpleNamespace

import pytest

from app.retrieval.incremental_index import IncrementalBaselineIndex
from config.retrieval import RetrievalConfig

from app.gateway.optimizer import MemoryOptimizer
from app.gateway.vault_manifest import scan_manifest
from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault
from config.optimizer import OptimizerConfig


def _note(path, text, mt=1_000_000_000_000_000_000):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mt, mt))


def _gateway(root, *, enabled=True, interval=0):
    vault = ObsidianVault(root)
    gw = SimpleNamespace(vault=vault, baseline=BaselineIndex(vault))
    gw.baseline.build()
    opt = MemoryOptimizer(OptimizerConfig(enabled=enabled, refresh_interval_s=interval))
    man = scan_manifest(vault)
    assert man is not None
    opt.mark_built(man.fp, man.files)
    return gw, opt


def test_disabled_optimizer_still_refreshes_lexical_index(tmp_path):
    p = tmp_path / "note.md"
    _note(p, "oldword")
    gw, opt = _gateway(tmp_path, enabled=False)
    _note(p, "newword", 1_100_000_000_000_000_000)
    assert opt.ensure_fresh(gw)["index_rebuilt"] is True
    assert gw.baseline.search("newword")
    assert not gw.baseline.search("oldword")


def test_negative_interval_explicitly_disables_freshness(tmp_path):
    p = tmp_path / "note.md"
    _note(p, "oldword")
    gw, opt = _gateway(tmp_path, interval=-1)
    _note(p, "newword", 1_100_000_000_000_000_000)
    assert opt.ensure_fresh(gw) == {}
    assert gw.baseline.search("oldword")
    assert not gw.baseline.search("newword")


def test_manifest_change_refreshes_despite_aggregate_collision(tmp_path):
    p = tmp_path / "note.md"
    _note(p, "oldword")
    _note(tmp_path / "future.md", "unrelated", 1_500_000_000_000_000_000)
    gw, opt = _gateway(tmp_path)
    before = scan_manifest(gw.vault)
    opt._prov = object()  # the metadata cache must not survive a manifest-only change
    opt._prov_fp = before.fp
    key = ("v", "newword", "baseline")
    opt.cache.put(key, ("ctx", [], [], {}, {"files": {}}))
    _note(p, "newword", 1_100_000_000_000_000_000)
    after = scan_manifest(gw.vault)
    assert before.fp == after.fp == gw.vault.fingerprint()
    assert before.files != after.files
    assert opt.ensure_fresh(gw)["index_rebuilt"] is True
    assert gw.baseline.search("newword")
    assert not gw.baseline.search("oldword")
    assert opt.cache.get(key) is None  # invalidate a previously negative result too
    assert opt._prov is None
    assert opt.ensure_fresh(gw)["index_rebuilt"] is False


@pytest.mark.parametrize("change", ["root", "extra_root", "excluded_dirs"])
def test_persistent_index_rejects_different_corpus_without_deleting_db(tmp_path, change):
    root = tmp_path / "vault"
    _note(root / "same.md", "oldword")
    vault = ObsidianVault(root)
    if change == "extra_root":
        _note(tmp_path / "extra1" / "same.md", "oldword")
        vault.add_extra_root("saved", tmp_path / "extra1")
    db = tmp_path / "index.db"
    first = IncrementalBaselineIndex(vault, db)
    first.build()
    first.close()
    other = ObsidianVault(root)
    if change == "root":
        _note(tmp_path / "other" / "same.md", "newword")
        other = ObsidianVault(tmp_path / "other")
    elif change == "extra_root":
        _note(tmp_path / "extra2" / "same.md", "newword")
        other.add_extra_root("saved", tmp_path / "extra2")
    else:
        other.excluded_dirs.add("excluded")
    with pytest.raises(ValueError, match="corpus"):
        IncrementalBaselineIndex(other, db).build()
    assert db.is_file()
    original = IncrementalBaselineIndex(vault, db)
    try:
        assert original.search("oldword")
        assert not original.search("newword")
        assert original.last_stats["unchanged"] >= 1
    finally:
        original.close()


def test_legacy_persistent_index_without_identity_fails_closed(tmp_path):
    root = tmp_path / "vault"
    _note(root / "same.md", "oldword")
    db = tmp_path / "index.db"
    first = IncrementalBaselineIndex(ObsidianVault(root), db)
    first.build()
    first.close()
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM meta WHERE k != 'schema'")
    with pytest.raises(ValueError, match="corpus"):
        IncrementalBaselineIndex(ObsidianVault(root), db).build()


@pytest.mark.parametrize("knob,value", [
    ("graphify_hybrid", False), ("graphify_text_seeds", 17),
    ("graphify_graph_expand", 23), ("graphify_query_budget", 3210),
    ("graphify_timeout_s", 42), ("graphify_stale_fallback_s", 1.5),
    ("ppr_enabled", True), ("ppr_alpha", 0.7),
    ("ppr_iters", 19), ("ppr_top_n", 7),
])
def test_cache_digest_tracks_graphify_and_ppr_knobs(tmp_path, monkeypatch, knob, value):
    monkeypatch.setattr("app.gateway.optimizer._experiments_digest", lambda gw: None)
    cfg = RetrievalConfig(vault_path=tmp_path, data_dir=tmp_path)
    gw = SimpleNamespace(
        retrieval_cfg=cfg, jev_cfg=None,
        optional_stages_cfg=SimpleNamespace(resolved=lambda pipeline: None),
        graphify=SimpleNamespace(graph_path=tmp_path / "missing-graph.json"),
    )
    opt = MemoryOptimizer()
    plan = opt.plan("newword", "graphify")
    before = opt.config_digest(gw, plan)
    assert getattr(cfg, knob) != value
    setattr(cfg, knob, value)
    assert opt.config_digest(gw, plan) != before
