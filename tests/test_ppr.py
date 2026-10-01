"""Tests for Personalized PageRank graph expansion (§5.5). No network, no real vault."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.retrieval import ppr
from app.retrieval.graphify_hybrid import GraphIndex, hybrid_search
from app.retrieval.pipelines import run_graphify, run_graphify_jev
from app.schemas.models import Candidate


def test_personalized_pagerank_conserves_mass_and_favours_neighbours():
    # triangle a-b-c plus an isolated hub d connected only to c
    adj = {"a": ["b", "c"], "b": ["a", "c"], "c": ["a", "b", "d"], "d": ["c"]}
    scores = ppr.personalized_pagerank(adj, {"a": 1.0}, alpha=0.85, iters=30)
    assert abs(sum(scores.values()) - 1.0) < 1e-6
    # a's direct neighbours must outrank the two-hop-away node d
    assert scores["b"] > scores["d"]
    assert scores["c"] > scores["d"]


def test_personalized_pagerank_empty_seeds_returns_empty():
    assert ppr.personalized_pagerank({"a": ["b"]}, {}) == {}
    assert ppr.personalized_pagerank({}, {"a": 1.0}) == {}


def _write_graph(path: Path) -> None:
    nodes = [
        {"id": "p1", "label": "nota-a", "node_kind": "page", "source_file": "a.md",
         "source_location": {"line": 1}},
        {"id": "h1", "label": "Secao", "node_kind": "heading", "source_file": "a.md",
         "source_location": {"line": 3}},
        {"id": "p2", "label": "nota-b", "node_kind": "page", "source_file": "b.md",
         "source_location": {"line": 1}},
        {"id": "p3", "label": "nota-c", "node_kind": "page", "source_file": "c.md",
         "source_location": {"line": 1}},
    ]
    links = [{"source": "p1", "target": "h1"}, {"source": "h1", "target": "p2"},
             {"source": "p2", "target": "p3"}]
    path.write_text(json.dumps({"nodes": nodes, "links": links}), encoding="utf-8")


def _fake_gw(rc, index):
    def _section_for(f, line):
        return SimpleNamespace(heading_path="Secao", line=line), f"corpo de {f}"

    bm_candidate = Candidate(candidate_id="c0:a.md#L1", source_file="a.md", section="Secao",
                             snippet="conteudo relevante da nota a", score=1.0, origin="baseline")

    return SimpleNamespace(
        retrieval_cfg=rc,
        graph_index=index,
        baseline=SimpleNamespace(search=lambda q, limit: [bm_candidate]),
        graphify=SimpleNamespace(_section_for=_section_for),
        vault=SimpleNamespace(read=lambda f: f"# {f}\n\nconteudo de {f}"),
        active_scope=None,
    )


def test_hybrid_search_ppr_disabled_matches_bfs_exactly(tmp_path):
    from config.retrieval import RetrievalConfig

    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    index = GraphIndex(graph_path)
    rc = RetrievalConfig(vault_path=tmp_path, ppr_enabled=False)
    gw = _fake_gw(rc, index)

    cands, metrics = hybrid_search(gw, "nota a", limit=10)
    assert metrics["graphify_expand_mode"] == "bfs"
    files = [c.source_file for c in cands]
    assert "b.md" in files  # BFS reaches b.md through h1


def test_hybrid_search_ppr_enabled_uses_ppr_expand(tmp_path):
    from config.retrieval import RetrievalConfig

    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    index = GraphIndex(graph_path)
    rc = RetrievalConfig(vault_path=tmp_path, ppr_enabled=True, ppr_top_n=5, ppr_iters=10)
    gw = _fake_gw(rc, index)

    cands, metrics = hybrid_search(gw, "nota a", limit=10)
    assert metrics["graphify_expand_mode"] == "ppr"
    files = [c.source_file for c in cands]
    # PPR should also reach b.md (one hop via the shared heading node)
    assert "b.md" in files


def test_hybrid_search_allow_ppr_false_forces_bfs_even_when_enabled(tmp_path):
    from config.retrieval import RetrievalConfig

    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    index = GraphIndex(graph_path)
    rc = RetrievalConfig(vault_path=tmp_path, ppr_enabled=True)
    gw = _fake_gw(rc, index)

    _, metrics = hybrid_search(gw, "nota a", limit=10, allow_ppr=False)
    assert metrics["graphify_expand_mode"] == "bfs"


def test_graphify_jev_pipeline_never_uses_ppr_even_when_flag_enabled(tmp_path, monkeypatch):
    """§5.5: graphify_jev is frozen. PPR_ENABLED must not change its output."""
    from config.retrieval import RetrievalConfig

    graph_path = tmp_path / "graph.json"
    _write_graph(graph_path)
    index = GraphIndex(graph_path)
    rc = RetrievalConfig(vault_path=tmp_path, ppr_enabled=True)
    gw = _fake_gw(rc, index)

    calls = {"ppr": 0}
    import app.retrieval.ppr as ppr_mod
    real_expand = ppr_mod.expand

    def _spy(*a, **kw):
        calls["ppr"] += 1
        return real_expand(*a, **kw)

    monkeypatch.setattr(ppr_mod, "expand", _spy)

    class _Jev:
        def evaluate(self, query, cands):
            for c in cands:
                c.decision = "KEEP"
                c.relevance = 0.9
            return cands, SimpleNamespace(to_dict=lambda: {
                "latency_ms": 0, "candidates_kept": len(cands), "candidates_review": 0,
                "candidates_dropped": 0, "candidates_quarantined": 0, "candidates_unjudged": 0,
                "input_tokens": 0, "output_tokens": 0, "cache_hits": 0, "cache_enabled": False,
            })

    run_graphify_jev(gw, "nota a", 5, jev=_Jev())
    assert calls["ppr"] == 0, "run_graphify_jev must never call PPR expansion (frozen pipeline)"

    run_graphify(gw, "nota a", 5)
    assert calls["ppr"] == 1, "run_graphify should use PPR expansion when PPR_ENABLED is set"
