from app.retrieval.baseline import BaselineIndex, query_terms
from app.services.obsidian import ObsidianVault


def idx(vault):
    return BaselineIndex(ObsidianVault(vault))


def test_accent_insensitive_match(tiny_vault):
    b = idx(tiny_vault)
    r1 = b.search("ferias")          # note has "Férias"
    r2 = b.search("decisao")         # note has "Decisão"
    assert any(c.source_file == "50-Pessoal/viagem-ferias.md" for c in r1)
    assert any(c.source_file == "20-Dev-IA/decisao-stack.md" for c in r2)
    assert all(c.origin == "baseline" for c in r1 + r2)


def test_stop_words_ignored(tiny_vault):
    assert query_terms("o que é a FastAPI para o backend") == ["fastapi", "backend"]
    b = idx(tiny_vault)
    assert b.search("o que é a de para") == []
    r = b.search("qual é a FastAPI")
    assert r and r[0].source_file == "20-Dev-IA/decisao-stack.md"


def test_empty_query(tiny_vault):
    b = idx(tiny_vault)
    assert b.search("") == []
    assert b.search("   ") == []


def test_deterministic_ordering(tiny_vault):
    q = "script configuração python backend viagem"
    a = [(c.candidate_id, c.score) for c in idx(tiny_vault).search(q)]
    b = [(c.candidate_id, c.score) for c in idx(tiny_vault).search(q)]
    assert a and a == b
    scores = [s for _, s in a]
    assert scores == sorted(scores, reverse=True)


def test_obsidian_dir_not_indexed(tiny_vault):
    b = idx(tiny_vault)
    b.build()
    assert b.files_indexed == 4
    assert all(".obsidian" not in c.source_file for c in b.search("hidden"))
