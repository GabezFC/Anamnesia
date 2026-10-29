"""F9-01 -- notas salvas por `memory_save` sob MG_SCOPE=projeto:X devem ser recuperadas pela busca escopada.

Causa: `Scope.matches(source_file)` só olhava o caminho (`saved_context/<arquivo>.md`) e ignorava o
frontmatter `projeto:` da nota. Tudo isolado em tmp: ANAMNESIA_HOME temporário (conftest), cópia do
vault sintético, pasta de notas salvas própria. Nunca toca o vault real.
"""
from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest

from app.memory_store.index import PREFIX, attach_saved_context
from app.services.scope import Scope, parse_scope

ROOT = Path(__file__).resolve().parents[1]
SYNTH = ROOT / "data" / "synthetic_vault"
TERM_X = "zirconiobravo"      # termo único salvo no projeto kraken
TERM_Y = "quartzodelta"       # termo único salvo no projeto aurora
TERM_P = "obsidianacaminho"   # termo único numa nota do vault em 30-Projetos/Kraken_Cerebro/


@pytest.fixture
def env(monkeypatch, tmp_path):
    if not SYNTH.is_dir():
        pytest.skip("vault sintético ausente")
    vault = tmp_path / "vault"
    shutil.copytree(SYNTH, vault)
    d = vault / "30-Projetos" / "Kraken_Cerebro"
    d.mkdir(parents=True, exist_ok=True)
    (d / "nota-caminho.md").write_text(f"---\ntitle: Caminho\ntype: nota\n---\n# Caminho\n\nO termo {TERM_P} vive no caminho do projeto.\n",
                                       encoding="utf-8")
    monkeypatch.setenv("MG_MCP_SAVE", "1")
    monkeypatch.setenv("MG_SCOPE", "projeto:kraken")
    monkeypatch.setenv("ANAMNESIA_SAVE_GATE", "enforce")
    from app.gateway.memory_gateway import MemoryGateway
    from app.memory_store.store import SavedContextStore
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig
    store = SavedContextStore(tmp_path / "home" / "saved_context", rate_per_min=100000)
    rc = RetrievalConfig(vault_path=vault, data_dir=tmp_path / "data")
    bc = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark", benchmark_mode=False)
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc)
    attach_saved_context(gw, store.root)
    gw.warm()
    import app.memory_store.store as st_mod
    monkeypatch.setattr(st_mod, "get_store", lambda: store)
    import app.mcp.server as srv
    srv = importlib.reload(srv)
    monkeypatch.setattr(srv, "_gateway", gw)
    return srv, gw, store, vault


def _files(gw, query, scope):
    r = gw.search(query, "baseline", 10, persist=False, scope=scope)
    return [s.file for s in r.sources]


def test_saved_note_is_found_by_scoped_search(env):
    srv, gw, store, vault = env
    res = srv.memory_save("Nota kraken", f"Decisão sintética: o termo {TERM_X} define o cache do kraken.")
    assert res.get("saved") is True, res
    note = store.get(res["id"])
    assert note.project == "kraken"                                   # gate preenche o projeto do escopo
    # via ferramenta MCP (escopo fixado por MG_SCOPE)
    out = srv.memory_search(TERM_X, pipeline="baseline")
    assert TERM_X in out.get("context", ""), out
    # via gateway com escopo explícito
    assert any(f.startswith(f"{PREFIX}/") for f in _files(gw, TERM_X, "projeto:kraken"))
    # sem escopo continua encontrando
    assert any(f.startswith(f"{PREFIX}/") for f in _files(gw, TERM_X, None))
    # escopo de OUTRO projeto não encontra (sem vazamento)
    assert not any(f.startswith(f"{PREFIX}/") for f in _files(gw, TERM_X, "projeto:aurora"))


def test_saved_note_of_other_project_is_not_visible_under_kraken(env):
    srv, gw, store, vault = env
    store.save("Nota aurora", f"O termo {TERM_Y} pertence ao projeto aurora.", project="aurora", trust="untrusted")
    from app.memory_store.index import reindex
    reindex(gw)
    assert not any(f.startswith(f"{PREFIX}/") for f in _files(gw, TERM_Y, "projeto:kraken"))
    assert any(f.startswith(f"{PREFIX}/") for f in _files(gw, TERM_Y, "projeto:aurora"))
    assert any(f.startswith(f"{PREFIX}/") for f in _files(gw, TERM_Y, None))
    # a ferramenta MCP, pinada em kraken, tampouco a devolve (cliente não alarga o escopo)
    out = srv.memory_search(TERM_Y, pipeline="baseline", scope="projeto:aurora")
    assert TERM_Y not in out.get("context", "")


def test_path_based_scope_still_works(env):
    srv, gw, store, vault = env
    assert any(f.startswith("30-Projetos/Kraken_Cerebro/") for f in _files(gw, TERM_P, "projeto:kraken"))
    assert not any(f.startswith("30-Projetos/Kraken_Cerebro/") for f in _files(gw, TERM_P, "projeto:aurora"))


def test_saved_note_without_project_is_excluded_from_project_scope(env):
    srv, gw, store, vault = env
    store.save("Sem projeto", "O termo frutaverdeneutra não pertence a projeto algum.", trust="untrusted")
    from app.memory_store.index import reindex
    reindex(gw)
    assert not any(f.startswith(f"{PREFIX}/") for f in _files(gw, "frutaverdeneutra", "projeto:kraken"))
    assert any(f.startswith(f"{PREFIX}/") for f in _files(gw, "frutaverdeneutra", None))


def test_scope_matches_accepts_frontmatter_unit():
    s = parse_scope("projeto:kraken")
    assert s.matches("saved_context/x-0123456789.md", "kraken")
    assert not s.matches("saved_context/x-0123456789.md", "aurora")
    assert not s.matches("saved_context/x-0123456789.md")
    assert isinstance(s, Scope)
