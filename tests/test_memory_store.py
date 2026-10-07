"""Fase 7: agent-saved context store (no network, no real data dir, never the real vault)."""
from __future__ import annotations

import threading
import zipfile
import io

import pytest

from app.memory_store import store as store_mod
from app.memory_store.index import PREFIX, attach_saved_context, reindex
from app.memory_store.store import (
    ConfirmationRequired, InvalidNoteId, InvalidNote, NoteNotFound, RateLimited, SavedContextStore,
    SecretDetected, TooLarge, scan_secrets, slugify,
)
from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault
from config.benchmark import BenchmarkConfig
from config.jev import JevConfig
from config.retrieval import RetrievalConfig


@pytest.fixture
def store(tmp_path):
    return SavedContextStore(tmp_path / "saved_context", rate_per_min=1000)


def test_save_get_roundtrip_and_frontmatter(store):
    nid = store.save("Decisão: usar FTS5", "Corpo da nota\n\ncom linhas.", ["a", "b"], "gateway", "claude")
    n = store.get(nid)
    assert (n.id, n.title, n.project, n.tags, n.source_agent) == (nid, "Decisão: usar FTS5", "gateway", ["a", "b"], "claude")
    assert n.content == "Corpo da nota\n\ncom linhas."
    assert n.created and n.updated
    f = store.root / n.file
    assert n.file.startswith("decisao-usar-fts5-") and n.file.endswith(f"-{nid}.md")
    text = f.read_text(encoding="utf-8")
    assert text.startswith("---\nid: " + nid)
    for key in ("title:", "project:", "tags:", "source_agent:", "created:", "updated:"):
        assert key in text


def test_slug_is_ascii_kebab_and_collisions_get_distinct_files(store):
    assert slugify("Ação  Rápida — Ünï/../x") == "acao-rapida-uni-x"
    assert slugify("???") == "nota"
    ids = {store.save("Mesmo título", f"conteúdo {i}") for i in range(5)}
    assert len(ids) == 5
    files = sorted(p.name for p in store.root.iterdir())
    assert len(files) == 5 and all(f.startswith("mesmo-titulo-") for f in files)


def test_atomic_write_crash_leaves_no_partial_file(store, monkeypatch):
    def boom(src, dst):
        raise OSError("crash between temp and replace")

    monkeypatch.setattr(store_mod, "_replace", boom)
    with pytest.raises(OSError):
        store.save("Nota", "conteúdo")
    assert list(store.root.iterdir()) == []  # no final file, no leftover temp
    monkeypatch.undo()
    assert store.list() == []


def test_readers_never_see_temp_files(store):
    (store.root).mkdir(parents=True)
    (store.root / ".tmp-abc.part").write_text("---\nparcial", encoding="utf-8")
    assert store.list() == []
    store.save("ok", "x y z")
    assert len(store.list()) == 1


def test_concurrent_saves_produce_distinct_valid_notes(tmp_path):
    st = SavedContextStore(tmp_path / "sc", rate_per_min=1000)
    ids, errs = [], []

    def work(i):
        try:
            ids.append(st.save("Nota concorrente", f"conteúdo número {i}", ["t"], None, f"agent{i}"))
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(set(ids)) == 8
    notes = st.list()
    assert len(notes) == 8
    assert {n.content for n in notes} == {f"conteúdo número {i}" for i in range(8)}
    assert len(list(st.root.iterdir())) == 8  # no temp leftovers


@pytest.mark.parametrize("secret", [
    "minha chave sk-abcdefghijklmnopqrstuvwx1234",
    "Authorization: Bearer abcdefghijklmnop1234567890",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "aws AKIAIOSFODNN7EXAMPLE",
    "token ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "OPENAI_API_KEY=abcdefghijklmnopqrstuvwxyz123456",
])
def test_secrets_are_rejected_and_never_stored(store, secret):
    with pytest.raises(SecretDetected) as ei:
        store.save("Notas", "contexto normal\n" + secret)
    assert "segredo" in str(ei.value)
    assert secret[:12] not in str(ei.value) or "BEGIN" in secret  # message names the kind, not the value
    assert not store.root.exists() or list(store.root.iterdir()) == []


def test_secret_in_title_or_tag_is_rejected(store):
    with pytest.raises(SecretDetected):
        store.save("sk-abcdefghijklmnopqrstuvwx1234", "ok")
    with pytest.raises(SecretDetected):
        store.save("ok", "ok", tags=["Bearer abcdefghijklmnop1234567890"])


def test_normal_text_is_not_flagged():
    assert scan_secrets("A skill 'sk-learn' e o token de acesso são conceitos. Bearer é um tipo.") == []


def test_size_cap(tmp_path):
    st = SavedContextStore(tmp_path / "sc", max_bytes=100, rate_per_min=1000)
    st.save("cabe", "x" * 100)
    with pytest.raises(TooLarge):
        st.save("nao cabe", "x" * 101)
    assert SavedContextStore(tmp_path / "d").max_bytes == 64 * 1024


def test_rate_cap_per_minute(tmp_path):
    now = [0.0]
    st = SavedContextStore(tmp_path / "sc", rate_per_min=3, clock=lambda: now[0])
    for i in range(3):
        st.save("n", f"c{i}")
    with pytest.raises(RateLimited):
        st.save("n", "c4")
    now[0] = 61.0
    st.save("n", "c5")


def test_validation(store):
    with pytest.raises(InvalidNote):
        store.save("", "x")
    with pytest.raises(InvalidNote):
        store.save("t", "   ")
    with pytest.raises(InvalidNote):
        store.save("a\nb", "x")


@pytest.mark.parametrize("bad", ["../etc/passwd", "..", "a/b", "ZZZZZZZZZZ", "", "0123456789ab", "x" * 300, "..\\x"])
def test_path_traversal_ids_rejected(store, bad):
    store.save("t", "c")
    for op in (store.get, store.delete):
        with pytest.raises(InvalidNoteId):
            op(bad)


def test_get_delete_missing(store):
    with pytest.raises(NoteNotFound):
        store.get("0123456789")
    nid = store.save("t", "c")
    store.delete(nid)
    with pytest.raises(NoteNotFound):
        store.get(nid)


def test_list_filters(store):
    store.save("a", "x", ["t1"], "p1")
    store.save("b", "y", ["t2"], "p2")
    assert [n.title for n in store.list(project="p1")] == ["a"]
    assert [n.title for n in store.list(tag="t2")] == ["b"]
    assert len(store.list()) == 2


def test_export_and_forget_all(store):
    store.save("a", "um")
    store.save("b", "dois")
    z = zipfile.ZipFile(io.BytesIO(store.export_zip()))
    names = z.namelist()
    assert len(names) == 2 and all(n.startswith("saved_context/") and n.endswith(".md") for n in names)
    with pytest.raises(ConfirmationRequired):
        store.forget_all()
    with pytest.raises(ConfirmationRequired):
        store.forget_all(confirm="yes")  # type: ignore[arg-type]
    assert len(store.list()) == 2
    assert store.forget_all(confirm=True) == 2
    assert store.list() == []
    assert zipfile.ZipFile(io.BytesIO(store.export_zip())).namelist() == []


# ---- search integration ------------------------------------------------------------------------

def _hits(vault, query):
    idx = BaselineIndex(vault)
    idx.build()
    return [c.source_file for c in idx.search(query, 10)]


def test_saved_note_is_searchable_and_vault_untouched(tiny_vault, tmp_path):
    vault = ObsidianVault(tiny_vault)
    before = vault.state_hash()
    st = SavedContextStore(tmp_path / "home" / "saved_context", rate_per_min=1000)
    attach_saved_context(vault, st.root)
    nid = st.save("Preferência de deploy", "O deploy sempre usa o canário zircônio antes do release.", ["deploy"])
    hits = _hits(vault, "canário zircônio")
    assert hits and hits[0].startswith(f"{PREFIX}/") and nid in hits[0]
    assert vault.state_hash() == before                      # user vault byte-identical
    assert not any(p.name.startswith("preferencia") for p in tiny_vault.rglob("*"))  # nothing written in it


def test_default_search_unchanged_when_folder_empty(tiny_vault, tmp_path):
    plain = ObsidianVault(tiny_vault)
    mounted = attach_saved_context(ObsidianVault(tiny_vault), tmp_path / "nope" / "saved_context")
    assert mounted.list_markdown() == plain.list_markdown()
    assert mounted.fingerprint() == plain.fingerprint()
    for q in ("stack backend FastAPI", "viagem praia"):
        assert _hits(mounted, q) == _hits(plain, q)
    (tmp_path / "empty").mkdir()
    assert attach_saved_context(ObsidianVault(tiny_vault), tmp_path / "empty").fingerprint() == plain.fingerprint()


def test_extra_root_cannot_escape(tiny_vault, tmp_path):
    from app.services.obsidian import VaultAccessError
    vault = attach_saved_context(ObsidianVault(tiny_vault), tmp_path / "sc")
    (tmp_path / "secret.md").write_text("x", encoding="utf-8")
    with pytest.raises(VaultAccessError):
        vault.read(f"{PREFIX}/../secret.md")


def _make_gateway(vault_path, tmp_path):
    from app.gateway.memory_gateway import MemoryGateway
    rcfg = RetrievalConfig(vault_path=vault_path, data_dir=tmp_path / "data")
    bcfg = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark")
    jcfg = JevConfig(model="jev-1.13.0", mode="performance", relevance_threshold=0.78, review_threshold=0.55,
                     injection_threshold=0.80, review_action="keep", failure_mode="fail_open", second_pass=False)

    class _G:  # graphify is irrelevant here (baseline pipeline only)
        graph_path = rcfg.mirror_dir / "graphify-out" / "graph.json"

        def build(self):
            return {}

    return MemoryGateway(retrieval_cfg=rcfg, jev_cfg=jcfg, bench_cfg=bcfg, graphify_service=_G())


def test_saved_today_retrieved_by_new_gateway_tomorrow(tiny_vault, tmp_path, monkeypatch):
    """Plan acceptance: an agent saves a note; a NEW gateway instance over the same folders finds it."""
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    st = store_mod.get_store()
    assert str(st.root).startswith(str(tmp_path / "home"))
    gw1 = attach_saved_context(_make_gateway(tiny_vault, tmp_path))
    gw1.warm()
    st.save("Acordo com cliente Orion", "O cliente Orion exige relatório quinzenal em PDF.", ["cliente"], "orion", "claude")
    del gw1  # "tomorrow": a fresh process/gateway
    gw2 = attach_saved_context(_make_gateway(tiny_vault, tmp_path / "other"))
    gw2.baseline.build()
    cands = gw2.retrieve("relatório quinzenal Orion", "baseline")
    assert cands and cands[0].source_file.startswith("saved_context/")
    assert "quinzenal" in cands[0].snippet
    # reindex makes a note saved AFTER build visible right away
    st.save("Outro fato", "A palavra rara é anfiguri.")
    reindex(gw2)
    assert any("anfiguri" in c.snippet for c in gw2.retrieve("anfiguri", "baseline"))


def test_gitignore_covers_saved_context():
    from pathlib import Path
    gi = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/*" in gi.splitlines()
