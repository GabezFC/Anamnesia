"""ANA-080: graph staleness is observable and self-repairing."""
from __future__ import annotations

import time

from app.services.graphify import GraphifyService
from app.services.obsidian import ObsidianVault


def _svc(tmp_path, monkeypatch, **kw):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "a.md").write_text("# A\n\nconteudo alfa\n", encoding="utf-8")
    svc = GraphifyService(ObsidianVault(vault_dir), tmp_path / "mirror", **kw)
    builds = []

    def fake_build(self, force=False):
        builds.append(1)
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        self.graph_path.write_text("{}", encoding="utf-8")
        self._save_fp()
        self._stale_since = None
        return {}

    monkeypatch.setattr(GraphifyService, "build", fake_build)
    monkeypatch.setattr(GraphifyService, "raw_query", lambda self, q, budget=None: "")
    return svc, vault_dir, builds


def test_fresh_then_stale_after_vault_change(tmp_path, monkeypatch):
    svc, vault_dir, _ = _svc(tmp_path, monkeypatch)
    assert svc.staleness()["graph_exists"] is False
    svc.build()
    assert svc.staleness()["graph_stale"] is False
    (vault_dir / "b.md").write_text("# B\n\nnova\n", encoding="utf-8")
    assert svc.staleness()["graph_stale"] is True


def test_search_reports_stale_and_refreshes_once(tmp_path, monkeypatch):
    svc, vault_dir, builds = _svc(tmp_path, monkeypatch)
    svc.build()
    (vault_dir / "b.md").write_text("# B\n\nnova\n", encoding="utf-8")
    _, info = svc.search("alfa")
    assert info["graph_stale"] is True
    svc._refresh_thread.join(5)
    assert len(builds) == 2
    _, info2 = svc.search("alfa")
    assert info2["graph_stale"] is False


def test_fallback_bm25_only_when_stale_too_long(tmp_path, monkeypatch):
    svc, vault_dir, _ = _svc(tmp_path, monkeypatch, stale_fallback_s=0.01)
    svc.build()
    (vault_dir / "b.md").write_text("# B\n\nnova\n", encoding="utf-8")
    monkeypatch.setattr(GraphifyService, "refresh_async", lambda self: False)   # keep it stale
    svc.search("alfa")
    time.sleep(0.05)
    cands, info = svc.search("alfa")
    assert cands == [] and info["graph_fallback"] == "bm25_only"


def test_dangling_candidates_counted(tmp_path, monkeypatch):
    svc, _, _ = _svc(tmp_path, monkeypatch)
    svc.build()
    out = "NODE gone [src=missing.md loc=L1]\nNODE ok [src=a.md loc=L1]\n"
    monkeypatch.setattr(GraphifyService, "raw_query", lambda self, q, budget=None: out)
    cands, info = svc.search("alfa")
    assert len(cands) == 1 and info["graph_dangling_candidates"] == 1
    assert info["graph_dangling_rate"] == 0.5
