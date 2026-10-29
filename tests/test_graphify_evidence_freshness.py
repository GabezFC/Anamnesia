"""Offline Graphify evidence regressions, using only synthetic notes."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.retrieval.baseline import BaselineIndex
from app.retrieval.experiments import RetrievalExperiments
from app.retrieval.graphify_hybrid import GraphIndex, hybrid_search
from app.services.dedup import deduplicate, preprocess
from app.services.graphify import GraphifyService
from app.services.obsidian import ObsidianVault
from config.retrieval import RetrievalConfig


@pytest.fixture
def graph_gateway(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Graph rebuild/subprocess forbidden in evidence tests")

    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr(GraphifyService, "build", forbidden)
    monkeypatch.setattr(GraphifyService, "refresh_async", forbidden)

    def make(notes):
        root = tmp_path / "vault"
        root.mkdir()
        for rel, text in notes.items():
            (root / rel).write_text(text, encoding="utf-8")
        vault = ObsidianVault(root)
        baseline = BaselineIndex(vault)
        baseline.build()
        graph = tmp_path / "graph.json"
        nodes = [dict(id=str(i), source_file=f, node_kind="page", label=f,
                      source_location={"line": 1}) for i, f in enumerate(notes)]
        graph.write_text(json.dumps({"nodes": nodes, "links": [
            {"source": "0", "target": str(i)} for i in range(1, len(nodes))
        ]}), encoding="utf-8")
        return SimpleNamespace(
            vault=vault, baseline=baseline, graph_index=GraphIndex(graph),
            graphify=GraphifyService(vault, tmp_path / "mirror"),
            retrieval_cfg=RetrievalConfig(vault_path=root),
            experiments=RetrievalExperiments(hybrid_score="rank"), active_scope=None,
        )

    return make


@pytest.mark.parametrize("allow_ppr", [True, False])
def test_hybrid_preserves_best_section_through_dedup(graph_gateway, allow_ppr):
    gw = graph_gateway({"a.md": (
        "# Nota\n\n## A incidental\n"
        "quartz e palavras genericas de preenchimento sem informacao util.\n\n"
        "## Z resposta\nquartz quartz quartz quartz quartz quartz quartz valor=742.\n"
    )})
    lexical = gw.baseline.search("quartz")
    assert "742" in lexical[0].snippet
    candidates, _ = hybrid_search(gw, "quartz", 100, allow_ppr=allow_ppr)
    delivered, _ = deduplicate(preprocess(candidates, 300), 1)
    assert delivered[0].section == lexical[0].section
    assert "742" in delivered[0].snippet
    assert candidates[0].score > candidates[1].score


def test_rank_keeps_file_bands_and_text_above_graph(graph_gateway):
    gw = graph_gateway({
        "a.md": "# Z best\nquartz quartz quartz quartz quartz quartz quartz\n\n## A weak\nquartz\n",
        "b.md": "# Other\nquartz quartz quartz\n",
        "c.md": "# Neighbor\nstructural context only\n",
    })
    lexical = gw.baseline.search("quartz")
    file_order = list(dict.fromkeys(c.source_file for c in lexical))
    section_order = {
        f: [c.section for c in lexical if c.source_file == f] for f in file_order
    }
    candidates, _ = hybrid_search(gw, "quartz", 100)
    text = [c for c in candidates if c.origin.endswith(":text")]
    graph = [c for c in candidates if c.origin.endswith(":graph")]
    assert graph
    assert min(c.score for c in text) > max(c.score for c in graph)
    for f in file_order:
        ranked = sorted([c for c in text if c.source_file == f], key=lambda c: -c.score)
        assert [c.section for c in ranked] == section_order[f]
        assert len({c.score for c in ranked}) == len(ranked)
    assert min(c.score for c in text if c.source_file == file_order[0]) > max(
        c.score for c in text if c.source_file == file_order[1]
    )


@pytest.mark.parametrize("preserve_stat", [False, True])
def test_cached_section_reflects_edit_without_graph_refresh(graph_gateway, preserve_stat):
    import os

    gw = graph_gateway({"a.md": "# Seed\nneedle\n", "b.md": "# Neighbor\noldword\n"})
    before, _ = hybrid_search(gw, "needle", 100)
    assert "oldword" in next(c.snippet for c in before if c.source_file == "b.md")
    path = gw.vault.root / "b.md"
    st = path.stat()
    path.write_text("# Neighbor\nnewword\n", encoding="utf-8")
    if preserve_stat:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        assert path.stat().st_size == st.st_size
        assert path.stat().st_mtime_ns == st.st_mtime_ns
    gw.baseline.build()
    assert gw.baseline.search("newword")
    after, _ = hybrid_search(gw, "needle", 100)
    body = next(c.snippet for c in after if c.source_file == "b.md")
    assert "newword" in body
    assert "oldword" not in body


def test_cached_deleted_neighbor_is_not_returned(graph_gateway):
    gw = graph_gateway({"a.md": "# Seed\nneedle\n", "b.md": "# Neighbor\noldword\n"})
    before, _ = hybrid_search(gw, "needle", 100)
    assert any(c.source_file == "b.md" for c in before)
    (gw.vault.root / "b.md").unlink()
    after, _ = hybrid_search(gw, "needle", 100)
    assert all(c.source_file != "b.md" for c in after)
    assert "b.md" not in gw.graphify._section_cache


def test_unchanged_content_reuses_split_and_denied_read_evicts(graph_gateway, monkeypatch):
    from unittest.mock import Mock
    from app.services.obsidian import split_sections

    gw = graph_gateway({"a.md": "# Seed\nneedle\n"})
    split = Mock(wraps=split_sections)
    monkeypatch.setattr("app.services.graphify.split_sections", split)
    first = gw.graphify._sections("a.md")
    assert gw.graphify._sections("a.md") is first
    assert split.call_count == 1
    monkeypatch.setattr(gw.vault, "read", Mock(side_effect=PermissionError("denied")))
    with pytest.raises(PermissionError):
        gw.graphify._sections("a.md")
    assert "a.md" not in gw.graphify._section_cache
