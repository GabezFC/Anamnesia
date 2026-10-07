"""Cache de candidatos dos scripts de diagnóstico: acerto, invalidação e --no-cache.

Vault temporário e `_graphify_candidates` falso (monkeypatch): o teste verifica a chave do cache,
nunca a recuperação real.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.schemas.models import Candidate
from app.retrieval import pipelines
from scripts import _candidate_cache as cc


def _cand(name: str) -> Candidate:
    return Candidate(candidate_id=name, source_file=f"{name}.md", section="S", snippet="t",
                     score=0.5, content_hash=name)


class FakeGraphify:
    """Stands in for `_graphify_candidates`: counts calls, returns a fresh list each time."""

    def __init__(self, names=("a", "b")):
        self.calls: list[tuple] = []
        self.names = list(names)

    def __call__(self, gw, query, allow_ppr=True):
        self.calls.append((gw, query, allow_ppr))
        return [_cand(n) for n in self.names], {"documents_found": len(self.names)}


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "10-Trabalho").mkdir(parents=True)
    (v / "10-Trabalho" / "nota-a.md").write_text("a\n", encoding="utf-8")
    (v / "10-Trabalho" / "nota-b.md").write_text("b\n", encoding="utf-8")
    return v


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeGraphify()
    monkeypatch.setattr(pipelines, "_graphify_candidates", f)
    monkeypatch.setattr(cc, "CACHE_DIR", tmp_path / "cache")  # never touch data/cache/ in a test
    return f


def _touch(path: Path, text: str) -> None:
    """Rewrite a note with different content, so mtime_ns AND size change."""
    path.write_text(text, encoding="utf-8")


# -- acerto / erro ------------------------------------------------------------------------------

def test_primeira_chamada_computa_e_grava(fake, vault, tmp_path):
    got = cc.cached_candidates("gw", vault, "q1")
    assert [c.candidate_id for c in got] == ["a", "b"]
    assert len(fake.calls) == 1
    assert fake.calls[0][2] is False  # allow_ppr=False, the frozen pipeline
    assert len(list((tmp_path / "cache").glob("*.pkl"))) == 1


def test_segunda_chamada_acerta_o_cache(fake, vault):
    first = cc.cached_candidates("gw", vault, "q1")
    second = cc.cached_candidates("gw", vault, "q1")
    assert len(fake.calls) == 1, "a segunda chamada não pode reexecutar a recuperação"
    assert [c.candidate_id for c in second] == [c.candidate_id for c in first]
    assert [c.section for c in second] == [c.section for c in first]


def test_perguntas_diferentes_tem_chaves_diferentes(fake, vault, tmp_path):
    cc.cached_candidates("gw", vault, "q1")
    cc.cached_candidates("gw", vault, "q2")
    assert len(fake.calls) == 2
    assert len(list((tmp_path / "cache").glob("*.pkl"))) == 2


def test_so_o_primeiro_elemento_e_usado_e_guardado(fake, vault, tmp_path):
    """`uniq` is cached; the metrics dict both scripts discard is not needed to answer."""
    got = cc.cached_candidates("gw", vault, "q1")
    payload = next(iter((tmp_path / "cache").glob("*.pkl")))
    import pickle
    stored = pickle.loads(payload.read_bytes())
    assert stored["candidates"] == got
    assert "metrics" not in stored


# -- invalidação --------------------------------------------------------------------------------

def test_editar_uma_nota_invalida_o_cache(fake, vault):
    cc.cached_candidates("gw", vault, "q1")
    _touch(vault / "10-Trabalho" / "nota-a.md", "a\n\nconteudo novo\n")
    cc.cached_candidates("gw", vault, "q1")
    assert len(fake.calls) == 2, "nota editada precisa reexecutar a recuperação"


def test_o_novo_resultado_substitui_o_antigo(fake, vault):
    cc.cached_candidates("gw", vault, "q1")
    _touch(vault / "10-Trabalho" / "nota-a.md", "a\n\nconteudo novo\n")
    fake.names = ["z"]
    got = cc.cached_candidates("gw", vault, "q1")
    assert [c.candidate_id for c in got] == ["z"]
    again = cc.cached_candidates("gw", vault, "q1")
    assert [c.candidate_id for c in again] == ["z"]
    assert len(fake.calls) == 2


def test_adicionar_nota_invalida_o_cache(fake, vault):
    cc.cached_candidates("gw", vault, "q1")
    (vault / "10-Trabalho" / "nota-c.md").write_text("c\n", encoding="utf-8")
    cc.cached_candidates("gw", vault, "q1")
    assert len(fake.calls) == 2


def test_rebuild_do_grafo_invalida_o_cache(fake, vault):
    graph = vault / "graphify-out" / "graph.json"
    graph.parent.mkdir(parents=True)
    graph.write_text("{}", encoding="utf-8")
    cc.cached_candidates("gw", vault, "q1")
    graph.write_text('{"nodes": []}', encoding="utf-8")
    # Deterministic: a coarse filesystem clock (seen on the Windows CI runner) can leave the mtime
    # unchanged for two quick writes; the fingerprint is mtime-based, so force a distinct one.
    st = graph.stat()
    os.utime(graph, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    cc.cached_candidates("gw", vault, "q1")
    assert len(fake.calls) == 2


def test_fingerprint_muda_com_a_nota_e_com_o_grafo(fake, vault, tmp_path):
    v2 = tmp_path / "outro-vault"
    (v2).mkdir()
    (v2 / "x.md").write_text("x\n", encoding="utf-8")
    antes = cc.vault_fingerprint(vault)
    assert cc.vault_fingerprint(v2) != antes
    _touch(vault / "10-Trabalho" / "nota-a.md", "a\n\nnovo\n")
    assert cc.vault_fingerprint(vault) != antes


def test_fingerprint_ignora_pastas_que_nao_tem_notas(fake, vault, tmp_path):
    antes = cc.vault_fingerprint(vault)
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.md").write_text("x\n", encoding="utf-8")
    (vault / ".git").mkdir()
    (vault / ".git" / "HEAD.md").write_text("ref\n", encoding="utf-8")
    assert cc.vault_fingerprint(vault) == antes


def test_arquivo_de_cache_corrompido_e_tratado_como_miss(fake, vault, tmp_path):
    cc.cached_candidates("gw", vault, "q1")
    for p in (tmp_path / "cache").glob("*.pkl"):
        p.write_bytes(b"nao-e-um-pickle")
    got = cc.cached_candidates("gw", vault, "q1")
    assert [c.candidate_id for c in got] == ["a", "b"]
    assert len(fake.calls) == 2


# -- --no-cache ----------------------------------------------------------------------------------

def test_no_cache_sempre_computa_e_nao_escreve(fake, vault, tmp_path):
    cc.cached_candidates("gw", vault, "q1", use_cache=False)
    cc.cached_candidates("gw", vault, "q1", use_cache=False)
    assert len(fake.calls) == 2
    assert not (tmp_path / "cache").exists() or not list((tmp_path / "cache").glob("*.pkl"))


def test_no_cache_nao_le_o_cache_ja_existente(fake, vault, tmp_path):
    cc.cached_candidates("gw", vault, "q1")  # popula
    fake.names = ["z"]
    got = cc.cached_candidates("gw", vault, "q1", use_cache=False)
    assert [c.candidate_id for c in got] == ["z"]
    assert len(fake.calls) == 2
    # e o que estava em disco continua intacto para a próxima chamada com cache
    assert [c.candidate_id for c in cc.cached_candidates("gw", vault, "q1")] == ["a", "b"]
    assert len(fake.calls) == 2


# -- wiring --------------------------------------------------------------------------------------

def test_scripts_registram_a_flag_no_cache():
    from scripts import check_jev_snippet, sweep_prefilter
    import inspect

    for module in (check_jev_snippet, sweep_prefilter):
        src = inspect.getsource(module.main)
        assert "--no-cache" in src, module.__name__
        assert "use_cache=not a.no_cache" in src, module.__name__


def test_scripts_nao_chamam_graphify_candidates_direto():
    """A geração de candidatos tem que passar pelo cache, senão a flag é decorativa."""
    import inspect

    from scripts import check_jev_snippet, sweep_prefilter
    for module in (check_jev_snippet, sweep_prefilter):
        src = inspect.getsource(module)
        assert "from app.retrieval.pipelines import _graphify_candidates" not in src, module.__name__
        assert "_graphify_candidates(" not in src, module.__name__
        assert "cached_candidates(" in src, module.__name__
