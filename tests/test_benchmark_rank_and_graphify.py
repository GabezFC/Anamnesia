"""ANA-012 (rank-aware metrics) and ANA-017 (graphify failure is a benchmark error)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.benchmark.runner import (BenchmarkRunner, GraphifyUnavailable, _expected_hits, fact_in_context,
                                  rank_metrics)


def test_mrr_ndcg_precision():
    m = rank_metrics(["a"], ["x", "a", "y"], k=3)
    assert m["mrr"] == 0.5 and m["precision_at_k"] == round(1 / 3, 4)
    assert 0 < m["ndcg"] < 1
    top = rank_metrics(["a"], ["a", "x"], k=2)
    assert top["mrr"] == 1.0 and top["ndcg"] == 1.0
    miss = rank_metrics(["a"], ["x", "y"], k=2)
    assert miss["mrr"] == 0.0 and miss["ndcg"] == 0.0


def test_ndcg_rewards_earlier_rank():
    assert rank_metrics(["a"], ["a", "x", "y"])["ndcg"] > rank_metrics(["a"], ["x", "y", "a"])["ndcg"]


def test_fact_in_context():
    hint = "o snapshot foi validado contra KrampusDB v7.111-rc0 em ambiente isolado"
    assert fact_in_context(hint, "Nota: o snapshot foi validado contra KrampusDB v7.111-rc0 em ambiente isolado")
    assert fact_in_context(hint, "texto sem relacao nenhuma") is False
    assert fact_in_context(None, "x") is None


def test_expected_hits_has_all_metrics():
    r = SimpleNamespace(sources=[SimpleNamespace(file="n1.md", section="S"), SimpleNamespace(file="n2.md", section="S")],
                        context="o snapshot foi validado contra KrampusDB isolado")
    q = {"expected_sources": ["n2.md"], "answer_hint": "snapshot validado contra KrampusDB isolado", "answerable": True}
    out = _expected_hits(q, r)
    assert out["recall"] == 1.0 and out["mrr"] == 0.5 and out["fact_in_context"] is True
    assert {"ndcg", "precision_at_k", "k"} <= set(out)


def test_unanswerable_has_no_fact_metric():
    r = SimpleNamespace(sources=[SimpleNamespace(file="n1.md", section="S")], context="x")
    out = _expected_hits({"expected_sources": ["n1.md"], "answer_hint": "abc", "answerable": False}, r)
    assert out["fact_in_context"] is None


def _gw(graphify_warm):
    return SimpleNamespace(graphify_warm=graphify_warm, bench_cfg=SimpleNamespace(seed=1, benchmark_mode=False),
                           jev_cfg=SimpleNamespace(__dict__={}), make_jev=lambda *a, **k: None,
                           db=SimpleNamespace(create_session=lambda *a, **k: None))


def test_runner_refuses_degraded_graphify():
    r = BenchmarkRunner(_gw({"error": "FileNotFoundError: [WinError 2]"}))
    with pytest.raises(GraphifyUnavailable):
        r.run([{"id": "q", "question": "x"}], pipelines=["graphify"], warmup=False)


def test_graphify_ok_flag():
    assert BenchmarkRunner(_gw({"error": "x"}))._graphify_ok("graphify") is False
    assert BenchmarkRunner(_gw({"nodes": 3}))._graphify_ok("graphify_jev") is True
    assert BenchmarkRunner(_gw({"error": "x"}))._graphify_ok("baseline") is None
