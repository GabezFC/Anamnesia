"""Tests for generic project discovery and query scoping (app/services/scope.py).

The hard requirement: adding a NEW project must work with zero code changes. Several tests use
invented project names that appear nowhere in the source to prove discovery is data-driven.
"""
from __future__ import annotations

from app.services.scope import (
    Scope,
    area_of,
    areas,
    discover,
    filter_paths,
    parse_scope,
    project_of,
    slug,
)

PATHS = [
    "30-Projetos/Norteia_Cerebro/decisoes/decisao-driver-asyncpg.md",
    "30-Projetos/Norteia_Cerebro/arquitetura/02-arquitetura.md",
    "30-Projetos/Memory_Gateway/componentes/jev.md",
    "20-Dev-IA/infra-memoria-agentes.md",
    "50-Pessoal/preferencias/preferencias-de-trabalho-com-agentes.md",
    "70-Daily/2026-09-19.md",
]


def test_slug_strips_accents_and_cerebro_suffix():
    assert slug("Norteia_Cerebro") == "norteia"
    assert slug("Memory_Gateway") == "memory-gateway"
    assert slug("Projeto Ação") == "projeto-acao"


def test_area_and_project_extraction():
    assert area_of(PATHS[0]) == "30-Projetos"
    assert project_of(PATHS[0]) == "norteia"
    assert project_of(PATHS[2]) == "memory-gateway"
    # a note directly under an area belongs to no project
    assert project_of("20-Dev-IA/infra-memoria-agentes.md") is None
    # 50-Pessoal/preferencias/ is a plain organisational subfolder, NOT a project container:
    # only subfolders of PROJECT_AREAS become projects.
    assert project_of(PATHS[4]) is None
    assert project_of("50-Pessoal/perfil/modo-de-agir-e-aprender.md") is None


def test_frontmatter_projeto_wins_over_path():
    p = "00-Inbox/rascunho-qualquer.md"
    assert project_of(p) is None
    assert project_of(p, frontmatter_projeto="Norteia_Cerebro") == "norteia"


def test_discover_is_generic_for_an_unknown_new_project():
    """A project name that appears nowhere in the codebase must be discovered automatically."""
    new = PATHS + [
        "30-Projetos/Trend_Monitor/arquitetura/visao-geral.md",
        "30-Projetos/Trend_Monitor/decisoes/decisao-fonte-de-noticias.md",
    ]
    reg = discover(new)
    assert "trend-monitor" in reg
    assert reg["trend-monitor"].note_count == 2
    assert reg["trend-monitor"].area == "30-Projetos"


def test_discover_counts_notes_per_project():
    reg = discover(PATHS)
    assert reg["norteia"].note_count == 2
    assert reg["memory-gateway"].note_count == 1


def test_areas_counts():
    a = areas(PATHS)
    assert a["30-Projetos"] == 3
    assert a["70-Daily"] == 1


def test_parse_scope_global_forms():
    for spec in (None, "", "global", "all", "*"):
        assert parse_scope(spec).is_global


def test_parse_scope_single_and_multi_project():
    assert parse_scope("projeto:norteia").projects == frozenset({"norteia"})
    s = parse_scope("projeto:norteia,projeto:memory-gateway")
    assert s.projects == frozenset({"norteia", "memory-gateway"})
    # bare token is treated as a project slug
    assert parse_scope("norteia").projects == frozenset({"norteia"})


def test_parse_scope_area():
    s = parse_scope("area:50-Pessoal")
    assert s.areas == frozenset({"50-Pessoal"}) and not s.projects


def test_scope_isolates_one_project():
    s = parse_scope("projeto:norteia")
    kept = filter_paths(PATHS, s)
    assert len(kept) == 2
    assert all("Norteia" in p for p in kept)
    # cross-contamination check: nothing from another project leaks in
    assert not any("Memory_Gateway" in p for p in kept)


def test_scope_union_of_two_projects():
    s = parse_scope("projeto:norteia,projeto:memory-gateway")
    assert len(filter_paths(PATHS, s)) == 3


def test_global_scope_keeps_everything():
    assert len(filter_paths(PATHS, Scope())) == len(PATHS)


def test_scope_label_roundtrip():
    s = parse_scope("projeto:norteia,area:50-Pessoal")
    # projects are listed before areas, each group sorted -> stable label for cache keys
    assert s.label() == "projeto:norteia,area:50-Pessoal"
    assert parse_scope(s.label()).projects == s.projects
    assert parse_scope(s.label()).areas == s.areas
    assert Scope().label() == "global"
