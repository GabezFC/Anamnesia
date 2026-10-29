"""Fase 6 / writing-block §8.2: os 10 testes de memória, de ponta a ponta no MemoryGateway REAL.

Vault, banco, índice e pasta de contexto salvo são TEMPORÁRIOS (tmp_path): nada toca dados do usuário.
Pipeline `baseline` (BM25/FTS5 local): zero rede, zero API paga. Reproduzir:
    .venv/Scripts/python.exe -m pytest tests/test_phase6_memory_certification.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.gateway.memory_gateway import MemoryGateway
from app.memory_store.index import attach_saved_context, reindex
from app.memory_store.lifecycle import save_checked
from app.memory_store.store import SavedContextStore
from app.services.scope import project_of
from config.benchmark import BenchmarkConfig
from config.retrieval import RetrievalConfig

A = "30-Projetos/Alfa_Cerebro"
B = "30-Projetos/Beta_Cerebro"


def _w(vault: Path, rel: str, text: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def lab(tmp_path):
    vault = tmp_path / "vault"
    _w(vault, f"{A}/Notes/porta-alfa.md", "# Porta Alfa\n\nO servidor do projeto alfa escuta na porta 4711 com zafira.\n")
    _w(vault, f"{A}/Notes/outra-alfa.md", "# Outra Alfa\n\nRotina de backup do alfa roda de madrugada.\n")
    _w(vault, f"{B}/Notes/porta-beta.md", "# Porta Beta\n\nO servidor do projeto beta escuta na porta 9022 com zafira.\n")
    saved = tmp_path / "data" / "saved_context"

    def make() -> MemoryGateway:
        gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=vault, data_dir=tmp_path / "data"),
                           bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "state" / "b.db"), profile="benchmark"))
        attach_saved_context(gw, saved)
        gw.baseline.build()
        return gw

    (tmp_path / "state").mkdir()
    return type("Lab", (), {"vault": vault, "saved": saved, "make": staticmethod(make), "tmp": tmp_path})


def files(r) -> list[str]:
    return [s.file for s in r.sources]


def q(gw, text, scope=None):
    return gw.search(text, pipeline="baseline", max_results=10, persist=False, scope=scope)


def test_memory_certification_10_steps(lab, monkeypatch):
    monkeypatch.setenv("MG_INCREMENTAL_INDEX", "1")   # índice persistente em disco (reinício = reuso)
    gw = lab.make()

    # 1. indexação inicial
    assert gw.baseline.last_stats["reindexed"] == 3 and gw.baseline.last_stats["files"] == 3

    # 2. consulta de informação existente
    r = q(gw, "porta do servidor alfa")
    assert files(r) and files(r)[0].endswith("porta-alfa.md")

    # 3. consulta de informação inexistente -> nada inventado
    r = q(gw, "xylofonquantico inexistente")
    assert files(r) == [] and (r.context or "").strip() == ""

    # 4+5. alteração de arquivo + reindexação incremental (só 1 arquivo)
    _w(lab.vault, f"{A}/Notes/porta-alfa.md", "# Porta Alfa\n\nAgora o alfa escuta na porta 5555 com quokkaunico.\n")
    gw.baseline.build()
    ls = gw.baseline.last_stats
    assert ls["reindexed"] == 1 and ls["unchanged"] == 2
    gw.optimizer.cache.clear()
    assert files(q(gw, "quokkaunico")) and not files(q(gw, "4711"))

    # 6. exclusão controlada de arquivo de teste (só no tmp)
    (lab.vault / A / "Notes" / "outra-alfa.md").unlink()
    gw.baseline.build()
    assert gw.baseline.last_stats["removed"] == 1
    gw.optimizer.cache.clear()
    assert not any(f.endswith("outra-alfa.md") for f in files(q(gw, "backup madrugada")))

    # 7. atualização da memória (contexto salvo por agente) -> pesquisável após reindex
    store = SavedContextStore(lab.saved)
    nid = store.save("Decisao cache", "Decidimos usar valkeyunico como cache do alfa.", tags=["t"], project="alfa")
    reindex(gw)
    r7 = q(gw, "valkeyunico")
    assert any("saved_context" in f for f in files(r7)) and "valkeyunico" in (r7.context or "")
    store.update(nid, content="Decidimos usar memcachedunico como cache do alfa.")
    reindex(gw)
    assert files(q(gw, "memcachedunico")) and not files(q(gw, "valkeyunico"))

    # 8. ausência de duplicações: mesma nota não aparece 2x e salvar conteúdo idêntico não cria 2ª nota
    r = q(gw, "zafira servidor porta")
    assert len(files(r)) == len(set(files(r)))
    n_before = len(list(lab.saved.glob("*.md")))
    skip = save_checked(store, "Decisao cache", "Decidimos usar memcachedunico como cache do alfa.", ["t"], "alfa", dedupe="skip")
    assert skip["saved"] is False and skip["duplicate_of"] == nid          # near-duplicate NÃO é gravado
    assert len(list(lab.saved.glob("*.md"))) == n_before
    warn = save_checked(store, "Decisao cache", "Decidimos usar memcachedunico como cache do alfa.", ["t"], "alfa", dedupe="warn")
    assert warn["saved"] is True and warn["similar"]                       # padrão `warn`: grava mas AVISA a duplicata
    store.delete(warn["id"])                                               # remove só a nota de teste (tmp)

    # 9. isolamento entre dois projetos
    ra = q(gw, "zafira porta servidor", scope="projeto:alfa")
    rb = q(gw, "zafira porta servidor", scope="projeto:beta")
    assert files(ra) and files(rb)
    assert {project_of(f) for f in files(ra)} == {"alfa"}
    assert {project_of(f) for f in files(rb)} == {"beta"}
    assert not (set(files(ra)) & set(files(rb)))

    # 10. persistência após reinicialização (novo MemoryGateway sobre os mesmos arquivos)
    gw.close()
    gw2 = lab.make()
    assert gw2.baseline.last_stats["reindexed"] == 0          # índice persistido reaproveitado
    assert files(q(gw2, "quokkaunico")) and files(q(gw2, "memcachedunico"))
    assert not files(q(gw2, "xylofonquantico"))
    gw2.close()
