"""M3: provenance, temporality (supersession/archived) and consistency.

Zero network, zero model call, tiny fixture vault. Two invariants are non-negotiable here:
the layer NEVER changes a candidate's identity and NEVER writes to the vault.
"""
from __future__ import annotations

import pytest

from app.gateway.optimizer import FROZEN_PIPELINES, MemoryOptimizer
from app.schemas.models import Candidate
from app.services.obsidian import ObsidianVault
from app.services.provenance import (HISTORICAL_MARKER, HISTORY_TERMS, NoteFacts,
                                     ProvenanceIndex, apply_temporal, parse_date,
                                     provenance_tokens, render_provenance, resolve_conflicts,
                                     wants_history)
from config.optimizer import OptimizerConfig


def C(cid, file, text="texto", score=1.0, section="Sec"):
    return Candidate(candidate_id=cid, source_file=file, section=section, snippet=text, score=score,
                     token_estimate=max(1, len(text) // 4))


def note(**fm) -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k.rstrip('_')}: {v}")
    lines += ["---", "", "# Nota", "", "corpo qualquer"]
    return "\n".join(lines)


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "30-Projetos" / "Memoria_Gateway" / "decisoes").mkdir(parents=True)
    (root / "99-Templates").mkdir(parents=True)
    base = "30-Projetos/Memoria_Gateway/decisoes"
    (root / base / "cache.md").write_text(note(
        id="a1", title="Cache é Redis", area="Projetos", type_="decisao", tags="[cache]",
        status="ativo", projeto="memoria-gateway", created="2026-09-01", updated="2026-09-01"),
        encoding="utf-8")
    (root / base / "cache-v2.md").write_text(note(
        id="a2", title="Cache é Valkey", area="Projetos", type_="decisao", tags="[cache]",
        status="ativo", projeto="memoria-gateway", created="2026-09-20", updated="2026-09-20",
        superseded_by="decisoes/cache.md"), encoding="utf-8")
    (root / base / "arquivada.md").write_text(note(
        id="a3", title="Nota antiga", area="Projetos", type_="nota", tags="[]",
        status="arquivado", projeto="memoria-gateway", created="2026-08-01", updated="2026-08-02"),
        encoding="utf-8")
    (root / base / "sem-frontmatter.md").write_text("sem frontmatter nenhum\n", encoding="utf-8")
    (root / "99-Templates" / "_nota.md").write_text(note(id="t", title="Template"), encoding="utf-8")
    return root


@pytest.fixture
def index(vault):
    return ProvenanceIndex(ObsidianVault(vault))


# -- facts -----------------------------------------------------------------------------------
def test_frontmatter_facts_are_read_and_absent_fields_stay_none(vault, index):
    f = index.facts("30-Projetos/Memoria_Gateway/decisoes/cache.md")
    assert (f.title, f.type_, f.status) == ("Cache é Redis", "decisao", "ativo")
    assert f.project_slug() == "memoria-gateway"
    assert f.touched.isoformat() == "2026-09-01"
    assert not f.is_historical
    sem = index.facts("30-Projetos/Memoria_Gateway/decisoes/sem-frontmatter.md")
    assert sem.title is None and sem.status is None and sem.has_frontmatter is False


def test_archived_and_superseded_are_both_historical(vault, index):
    sup = index.facts("30-Projetos/Memoria_Gateway/decisoes/cache-v2.md")
    arc = index.facts("30-Projetos/Memoria_Gateway/decisoes/arquivada.md")
    assert sup.is_historical and not sup.is_archived and sup.superseded_by.endswith("cache.md")
    assert arc.is_historical and arc.is_archived
    assert not index.facts("30-Projetos/Memoria_Gateway/decisoes/cache.md").is_historical


def test_missing_note_degrades_to_unknowns_instead_of_raising(index):
    f = index.facts("30-Projetos/Memoria_Gateway/decisoes/nao-existe.md")
    assert f.path.endswith("nao-existe.md") and f.title is None and not f.is_historical


@pytest.mark.parametrize("raw,expected", [("2026-09-20", "2026-09-20"), ("2026-09-20 14:43", "2026-09-20"),
                                          ("'2026-09-20T14:43'", "2026-09-20"), ("", None),
                                          ("amanhã", None), (None, None)])
def test_parse_date_is_forgiving_but_never_invents(raw, expected):
    got = parse_date(raw)
    assert (got.isoformat() if got else None) == expected


# -- provenance line -------------------------------------------------------------------------
def test_provenance_line_states_where_from_and_adds_no_authority(index):
    line = index.line("30-Projetos/Memoria_Gateway/decisoes/cache.md")
    assert line.startswith("[fonte: cache · decisao · ativo · atualizado 2026-09-01 · "
                           "projeto memoria-gateway]")
    # It must not repeat the data-framing sentence (the context header owns that) nor invent
    # authority words -- one fact per field, no instruction to the consumer.
    low = line.lower()
    for forbidden in ("treat", "instrucao", "instrução", "obedeça", "ignore", "confiavel",
                      "verdadeiro", "fato"):
        assert forbidden not in low


def test_missing_fields_render_as_unknown_not_as_emptiness(index):
    line = index.line("30-Projetos/Memoria_Gateway/decisoes/sem-frontmatter.md")
    # type, status and updated are unknown. The project is NOT: the path declares it
    # (app/services/scope.py), so the line stays useful for a note with no frontmatter at all.
    assert line.count("?") == 3, line
    assert line == ("[fonte: sem-frontmatter · ? · ? · atualizado ? · projeto memoria-gateway]")


def test_provenance_token_cost_is_measured_and_non_zero(index):
    lines = [index.line("30-Projetos/Memoria_Gateway/decisoes/cache.md"),
             index.line("30-Projetos/Memoria_Gateway/decisoes/arquivada.md")]
    cost = provenance_tokens(lines)
    assert cost == sum(len(l) // 4 or 1 for l in lines) or cost > 0
    assert provenance_tokens([]) == 0


def test_render_provenance_uses_touched_date_when_updated_is_absent():
    f = NoteFacts(path="x/y.md", title="T", created=parse_date("2026-01-02"))
    assert "atualizado 2026-01-02" in render_provenance(f)


# -- temporality -----------------------------------------------------------------------------
def test_history_query_detection_is_accent_and_phrase_aware():
    assert wants_history("o que mudou nessa decisão?")
    assert wants_history("qual era a versão anterior do cache?")
    assert wants_history("histórico das decisões do vault")
    assert not wants_history("qual o driver do projeto?")
    assert not wants_history("")
    # every term must be accent-folded, or the detector would miss real Portuguese queries
    assert all(not t.isascii() or t in HISTORY_TERMS for t in HISTORY_TERMS)


def test_archived_note_is_demoted_but_still_reachable_by_default(index):
    cands = [C("c1", "30-Projetos/Memoria_Gateway/decisoes/cache.md", score=1.0),
             C("c2", "30-Projetos/Memoria_Gateway/decisoes/arquivada.md", score=1.0)]
    out, m = apply_temporal(cands, index, history_wanted=False, demote_factor=0.5)
    assert [c.candidate_id for c in out] == ["c1", "c2"], "demotion must not delete a source"
    assert out[1].score == 0.5 and out[1].meta["historical"] is True
    assert m["memory_historical_demoted"] == 1 and m["memory_historical_excluded"] == 0


def test_history_query_stops_the_demotion_and_keeps_the_mark(index):
    cands = [C("c2", "30-Projetos/Memoria_Gateway/decisoes/arquivada.md", score=1.0)]
    out, m = apply_temporal(cands, index, history_wanted=True, demote_factor=0.5)
    assert out[0].score == 1.0 and out[0].meta["historical"] is True
    assert not out[0].meta.get("temporal_demoted")
    assert m["memory_history_requested"] is True and m["memory_historical_demoted"] == 0


def test_strict_mode_is_opt_in_and_only_answers_history_queries(index):
    cands = [C("c2", "30-Projetos/Memoria_Gateway/decisoes/arquivada.md", score=1.0)]
    out, m = apply_temporal(cands, index, history_wanted=False, demote_factor=0.5, exclude=True)
    assert out == [] and m["memory_historical_excluded"] == 1
    out2, m2 = apply_temporal(list(cands), index, history_wanted=True, demote_factor=0.5,
                               exclude=True)
    assert [c.candidate_id for c in out2] == ["c2"] and m2["memory_historical_excluded"] == 0


def test_historical_marker_only_for_historical_notes(index):
    assert index.marker("30-Projetos/Memoria_Gateway/decisoes/arquivada.md") == HISTORICAL_MARKER
    assert index.marker("30-Projetos/Memoria_Gateway/decisoes/cache.md") == ""


def test_temporal_layer_is_a_noop_without_index_or_candidates():
    cands = [C("c1", "a.md")]
    assert apply_temporal(cands, None, False, 0.5)[1]["memory_historical_total"] == 0
    assert apply_temporal([], None, False, 0.5)[0] == []


# -- consistency -----------------------------------------------------------------------------
def test_same_title_conflict_demotes_the_older_and_keeps_both(tmp_path, index):
    (tmp_path / "vault" / "30-Projetos" / "Memoria_Gateway" / "decisoes" / "cache-old.md").write_text(
        note(id="a0", title="Cache é Redis", type_="decisao", status="ativo", projeto="memoria-gateway",
             created="2026-08-01", updated="2026-08-01"), encoding="utf-8")
    cands = [C("old", "30-Projetos/Memoria_Gateway/decisoes/cache-old.md", score=0.9),
             C("new", "30-Projetos/Memoria_Gateway/decisoes/cache.md", score=0.9)]
    out, m = resolve_conflicts(cands, index, demote_factor=0.5, overlap=0.6)
    assert len(out) == 2, "a conflict is a signal, never a deletion"
    winner = {c.candidate_id: c for c in out}
    assert winner["new"].score == 0.9 and "conflict" not in (winner["new"].meta or {})
    assert winner["old"].score == 0.45
    assert winner["old"].meta["conflict"]["with"].endswith("cache.md")
    assert m["memory_conflicts_detected"] == 1 and m["memory_conflict_same_title"] == 1


def test_overlap_detector_ignores_two_sections_written_on_the_same_day(tmp_path, index):
    d = tmp_path / "vault" / "30-Projetos" / "Memoria_Gateway" / "decisoes"
    (d / "parte1.md").write_text(note(id="p1", title="Parte 1", status="ativo",
                                      projeto="memoria-gateway", created="2026-09-20",
                                      updated="2026-09-20"), encoding="utf-8")
    (d / "parte2.md").write_text(note(id="p2", title="Parte 2", status="ativo",
                                      projeto="memoria-gateway", created="2026-09-20",
                                      updated="2026-09-20"), encoding="utf-8")
    body = ("usamos valkey porque o redis mudou de licenca e o custo caiu bastante "
            "para o time inteiro no mes corrente")
    cands = [C("p1", "30-Projetos/Memoria_Gateway/decisoes/parte1.md", text=body, score=1.0),
             C("p2", "30-Projetos/Memoria_Gateway/decisoes/parte2.md", text=body, score=1.0)]
    _, m = resolve_conflicts(cands, index, demote_factor=0.5, overlap=0.6)
    assert m["memory_conflict_overlap"] == 0


def test_equal_dates_are_resolved_deterministically_not_by_arrival_order(tmp_path, index):
    """Two notes, same title, SAME date and same score: there is no "newer", so the tie-break has to
    be reproducible instead of depending on retrieval order."""
    d = tmp_path / "vault" / "30-Projetos" / "Memoria_Gateway" / "decisoes"
    for name, cid in (("empate-a.md", "z"), ("empate-b.md", "y")):
        (d / name).write_text(note(id=cid, title="Empate", status="ativo",
                                   projeto="memoria-gateway", created="2026-09-20",
                                   updated="2026-09-20"), encoding="utf-8")
    p = "30-Projetos/Memoria_Gateway/decisoes/"
    runs = []
    for order in (("a", "b"), ("b", "a")):
        cands = [C(order[0] + "-cid", p + f"empate-{order[0]}.md", score=0.5),
                 C(order[1] + "-cid", p + f"empate-{order[1]}.md", score=0.5)]
        out, _ = resolve_conflicts(cands, index, demote_factor=0.5, overlap=0.6)
        runs.append(tuple(sorted((c.candidate_id, round(c.score, 6)) for c in out)))
    assert runs[0] == runs[1], "same input, same verdict"


def test_conflict_detector_needs_two_candidates(index):
    assert resolve_conflicts([C("a", "x.md")], index, 0.5, 0.6)[1]["memory_conflicts_detected"] == 0


# -- integration with the layer --------------------------------------------------------------
def test_flags_can_default_off_in_a_block(vault):
    cfg = OptimizerConfig.disabled()
    assert not (cfg.provenance or cfg.temporal_demote or cfg.conflict_check)


def test_frozen_pipeline_is_a_noop_even_with_every_flag_on():
    assert "graphify_jev" in FROZEN_PIPELINES
    assert OptimizerConfig().temporal_demote and OptimizerConfig().conflict_check

def test_provenance_is_off_by_default():
    # +23.6% context tokens for no measured recall/fact gain (bench 2026-10-02): opt-in only.
    assert OptimizerConfig().provenance is False
