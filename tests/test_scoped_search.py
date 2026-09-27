"""Integration tests for scoped search through the gateway (§14, §40).

These use the REAL vault (read-only) because the point is to prove that project isolation holds
against actual data, not a fixture. A mock JEV backend keeps the paid judge out of the tests.
"""
from __future__ import annotations

import pytest

from app.gateway.memory_gateway import MemoryGateway
from app.services.scope import project_of


class MockJevBackend:
    """Judges everything as highly relevant, so scope is the only thing that can filter."""

    def evaluate(self, state, questions):
        n = len([k for k in questions if k.startswith("rel_")])
        answers = {f"rel_{i}": 0.95 for i in range(n)}
        return answers, {"input_tokens": n * 300, "output_tokens": n * 18}, "mock-jev"


@pytest.fixture(scope="module")
def gateway():
    gw = MemoryGateway(jev_backend=MockJevBackend())
    if not gw.vault.exists():
        pytest.skip("vault não disponível neste ambiente")
    gw.jev = gw.make_jev(gw.jev_cfg, cache=False)
    gw.warm()
    return gw


QUERY = "arquitetura decisao driver banco de dados"


def test_projects_endpoint_is_generic(gateway):
    info = gateway.projects()
    assert info["total_notes"] > 0
    slugs = {p["slug"] for p in info["projects"]}
    # discovered from the filesystem, never hardcoded in the source
    assert slugs, "nenhum projeto descoberto"
    for p in info["projects"]:
        assert p["note_count"] > 0 and p["area"]


def test_global_search_returns_context(gateway):
    r = gateway.search(QUERY, pipeline="baseline", max_results=10, persist=False)
    assert r.metrics["scope"] == "global"
    assert r.sources, "busca global não retornou fontes"


@pytest.mark.parametrize("pipeline", ["baseline", "graphify_jev"])
def test_project_scope_isolates_sources(gateway, pipeline):
    """Every source returned under a project scope must belong to that project."""
    info = gateway.projects()
    if not info["projects"]:
        pytest.skip("vault sem projetos")
    slug = info["projects"][0]["slug"]
    r = gateway.search(QUERY, pipeline=pipeline, max_results=10, persist=False,
                       scope=f"projeto:{slug}")
    assert r.metrics["scope"] == f"projeto:{slug}"
    for s in r.sources:
        assert project_of(s.file) == slug, f"vazamento de escopo: {s.file}"


def test_area_scope_isolates_sources(gateway):
    r = gateway.search("preferencias de trabalho com agentes", pipeline="baseline",
                       max_results=10, persist=False, scope="area:50-Pessoal")
    assert r.metrics["scope"] == "area:50-Pessoal"
    for s in r.sources:
        assert s.file.startswith("50-Pessoal/"), f"vazamento de escopo: {s.file}"


def test_multi_project_scope_is_a_union(gateway):
    info = gateway.projects()
    if len(info["projects"]) < 2:
        pytest.skip("vault com menos de dois projetos")
    a, b = info["projects"][0]["slug"], info["projects"][1]["slug"]
    r = gateway.search(QUERY, pipeline="baseline", max_results=20, persist=False,
                       scope=f"projeto:{a},projeto:{b}")
    for s in r.sources:
        assert project_of(s.file) in {a, b}, f"vazamento de escopo: {s.file}"


def test_scope_reduces_judge_input(gateway):
    """A narrow scope must cost FEWER judge tokens than global: scoping happens before the judge."""
    wide = gateway.search(QUERY, pipeline="graphify_jev", max_results=10, persist=False)
    info = gateway.projects()
    if not info["projects"]:
        pytest.skip("vault sem projetos")
    narrow = gateway.search(QUERY, pipeline="graphify_jev", max_results=10, persist=False,
                            scope=f"projeto:{info['projects'][0]['slug']}")
    assert narrow.metrics["documents_sent_to_jev"] <= wide.metrics["documents_sent_to_jev"]


def test_total_tokens_spent_is_consistent(gateway):
    r = gateway.search(QUERY, pipeline="graphify_jev", max_results=10, persist=False)
    m = r.metrics
    assert m["total_tokens_spent"] == m["judge_tokens"] + m["context_tokens"]
    if m["context_tokens"]:
        assert m["token_amplification"] == pytest.approx(
            m["total_tokens_spent"] / m["context_tokens"], rel=0.01)


def test_baseline_spends_no_judge_tokens(gateway):
    m = gateway.search(QUERY, pipeline="baseline", max_results=10, persist=False).metrics
    assert m["judge_tokens"] == 0
    assert m["total_tokens_spent"] == m["context_tokens"]
