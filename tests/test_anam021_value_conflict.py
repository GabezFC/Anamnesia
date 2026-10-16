"""ANAM-021 / AUD-015: conflito por VALOR (números/entidades), não só Jaccard de shingles."""
from __future__ import annotations

import pytest

from app.services.near_dup import jaccard, shingles
from app.services.obsidian import ObsidianVault
from app.services.provenance import ProvenanceIndex, resolve_conflicts, value_conflict
from tests.test_provenance import C, note

B = "30-Projetos/Memoria_Gateway/decisoes"

# (older, newer, tipo): pares conflitantes -- mesmo assunto, valores divergentes dos dois lados
CONFLICTING = [
    ("O TTL do cache de busca fica em 30 segundos para todos os usuarios do gateway",
     "O TTL do cache de busca fica em 60 segundos para todos os usuarios do gateway", "numbers"),
    ("A taxa de aprovacao minima do benchmark e 85% antes de promover o roteador para producao",
     "A taxa de aprovacao minima do benchmark e 92% antes de promover o roteador para producao", "numbers"),
    ("Decisao: o cache semantico do gateway usa Redis como backend padrao em producao",
     "Decisao: o cache semantico do gateway usa Valkey como backend padrao em producao", "entities"),
]
# pares NÃO conflitantes: um lado só acrescenta informação / assuntos diferentes
COMPATIBLE = [
    ("O TTL do cache de busca fica em 30 segundos para todos os usuarios",
     "O TTL do cache de busca fica em 30 segundos para todos os usuarios e o limite e 30 itens"),
    ("O cache semantico do gateway usa Redis como backend padrao em producao",
     "O cache semantico do gateway usa Redis como backend padrao em producao hoje"),
    ("Reuniao de planejamento marcada para 10 pessoas na sala azul do predio central",
     "Orcamento mensal de infraestrutura limitado a 500 dolares para o time de plataforma"),
]


@pytest.mark.parametrize("a,b,kind", CONFLICTING)
def test_value_conflict_detects_divergent_values(a, b, kind):
    assert value_conflict(a, b) == kind
    assert value_conflict(b, a) == kind, "simétrico"


@pytest.mark.parametrize("a,b", COMPATIBLE)
def test_value_conflict_ignores_compatible_pairs(a, b):
    assert value_conflict(a, b) is None


def test_dates_alone_are_not_values():
    a = "Revisado em 2026-09-01 o cache usa o backend padrao do gateway em producao"
    b = "Revisado em 2026-09-20 o cache usa o backend padrao do gateway em producao"
    assert value_conflict(a, b) is None


@pytest.fixture
def index(tmp_path):
    d = tmp_path / "vault" / B
    d.mkdir(parents=True)
    (tmp_path / "vault" / "99-Templates").mkdir()
    for name, upd in (("ttl-old.md", "2026-08-01"), ("ttl-new.md", "2026-09-20")):
        (d / name).write_text(note(id=name, title=name, status="ativo", projeto="memoria-gateway",
                                   created=upd, updated=upd), encoding="utf-8")
    return ProvenanceIndex(ObsidianVault(tmp_path / "vault"))


@pytest.mark.parametrize("old,new,kind", CONFLICTING)
def test_resolve_conflicts_flags_value_conflict_below_jaccard_threshold(index, old, new, kind):
    assert jaccard(shingles(old, 5), shingles(new, 5)) < 0.9, "o caso do problema: Jaccard sozinho não pega"
    cands = [C("old", f"{B}/ttl-old.md", old, 0.9), C("new", f"{B}/ttl-new.md", new, 0.9)]
    out, m = resolve_conflicts(cands, index, demote_factor=0.5, overlap=0.9)
    by = {c.candidate_id: c for c in out}
    assert len(out) == 2, "conflito é sinal, nunca remoção"
    assert by["old"].score == 0.45 and by["new"].score == 0.9
    assert by["old"].meta["conflict"]["reason"] == f"value_{kind}"
    assert m["memory_conflict_value"] == 1 and m["memory_conflicts_detected"] == 1


@pytest.mark.parametrize("old,new", COMPATIBLE)
def test_resolve_conflicts_leaves_compatible_pairs_alone(index, old, new):
    cands = [C("old", f"{B}/ttl-old.md", old, 0.9), C("new", f"{B}/ttl-new.md", new, 0.9)]
    out, m = resolve_conflicts(cands, index, demote_factor=0.5, overlap=0.9)
    assert [c.score for c in out] == [0.9, 0.9] and m["memory_conflicts_detected"] == 0


def test_same_date_is_exempt_from_value_conflict(index, tmp_path):
    d = tmp_path / "vault" / B
    (d / "ttl-new2.md").write_text(note(id="n2", title="n2", status="ativo", projeto="memoria-gateway",
                                        created="2026-09-20", updated="2026-09-20"), encoding="utf-8")
    a, b, _ = CONFLICTING[0]
    cands = [C("x", f"{B}/ttl-new.md", a, 0.9), C("y", f"{B}/ttl-new2.md", b, 0.9)]
    _, m = resolve_conflicts(cands, index, 0.5, 0.9)
    assert m["memory_conflicts_detected"] == 0
