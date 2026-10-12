"""Onda 3 -- Memória + provenance (ANA-145 .. ANA-163). Everything runs offline, on temp dirs."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.memory_store import lifecycle as lc
from app.memory_store.index import PREFIX, attach_saved_context, reindex
from app.memory_store.store import (
    InvalidNote, NoteNotFound, SavedContextError, SavedContextStore, content_digest, parse, render,
)
from app.services.obsidian import ObsidianVault


@pytest.fixture
def store(tmp_path):
    return SavedContextStore(tmp_path / "home" / "saved_context", rate_per_min=100000)


def _gateway(tiny_vault, tmp_path, store):
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig
    rc = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    bc = BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark", benchmark_mode=False)
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc)
    attach_saved_context(gw, store.root)
    gw.warm()
    return gw


# ============================ ANA-145: schema v2 ============================
def test_new_note_is_valid_v2(store):
    nid = store.save("Cache", "Usamos Redis na versão 7.", ["cache"], "anamnesia", "hermes", kind="decision",
                     ttl_days=30, confidence=0.8, source="run:abc123")
    n = store.get(nid)
    assert n.schema == 2 and n.kind == "decision" and n.status == "active"
    assert n.source == "run:abc123" and n.confidence == 0.8
    assert n.expires_at and not n.is_expired()
    assert n.content_sha256 == content_digest("Usamos Redis na versão 7.") and n.integrity_ok() is True


def test_defaults_never_leave_source_empty_and_never_invent_confidence(store):
    a = store.get(store.save("A", "conteudo a", source_agent="claude"))
    b = store.get(store.save("B", "conteudo b"))
    assert a.source == "agent:claude" and b.source == "manual"
    assert a.kind == "episodic" and a.confidence is None   # confidence only when declared (ANA-243)


@pytest.mark.parametrize("kw", [{"kind": "banana"}, {"confidence": 1.5}, {"confidence": -0.1},
                                {"expires_at": "ontem"}, {"ttl_days": 0}, {"ttl_days": -3}, {"ttl_days": "x"}])
def test_invalid_v2_values_are_rejected_and_nothing_written(store, kw):
    with pytest.raises(InvalidNote):
        store.save("T", "corpo", **kw)
    assert not store.root.exists() or not list(store.root.iterdir())


def test_v1_file_is_still_readable_and_rerenders_identically(store, monkeypatch):
    monkeypatch.setenv("MG_MEMORY_SCHEMA_V2", "0")           # a genuine v1 file, written by the v1 code path
    nid = store.save("Velha", "corpo antigo", ["t"], "proj", "hermes")
    monkeypatch.delenv("MG_MEMORY_SCHEMA_V2")
    p = store._path_for(nid)
    v1 = p.read_text(encoding="utf-8")
    assert "schema:" not in v1 and "kind:" not in v1 and "content_sha256" not in v1
    n = store.get(nid)
    assert n.schema == 1 and n.kind is None and n.integrity_ok() is None and not n.is_expired()
    assert render(n) == v1  # no v2 key leaks into a v1 file
    assert parse(v1, p.name) == n


def test_schema_v2_rollback_flag_writes_v1(store, monkeypatch):
    monkeypatch.setenv("MG_MEMORY_SCHEMA_V2", "0")
    n = store.get(store.save("T", "corpo"))
    assert n.schema == 1 and n.kind is None
    with pytest.raises(InvalidNote):
        store.save("T2", "corpo", kind="fact")


def test_tampered_note_fails_integrity(store):
    nid = store.save("T", "texto original")
    p = store._path_for(nid)
    p.write_text(p.read_text(encoding="utf-8").replace("texto original", "texto ALTERADO"), encoding="utf-8")
    assert store.get(nid).integrity_ok() is False
    assert nid in lc.audit(store)["integrity_failures"]


def test_secret_in_new_field_is_rejected(store):
    with pytest.raises(SavedContextError):
        store.save("T", "ok", source="sk-abcdefghijklmnopqrstuvwxyz0123456789")
    assert not store.root.exists() or not list(store.root.iterdir())


# ===== ANA-146: temporal/provenance layer applies to saved_context =====
def test_saved_superseded_note_is_historical_and_new_one_is_current(tiny_vault, tmp_path, store):
    from app.services.provenance import ProvenanceIndex
    old = store.save("Cache antigo", "O cache do gateway usa Memcached.", kind="decision")
    new = store.save("Cache novo", "O cache do gateway usa Redis.", kind="decision", supersedes=old)
    assert store.get(old).status == "superseded" and store.get(old).superseded_by == new
    assert store.get(new).supersedes == old
    vault = attach_saved_context(ObsidianVault(tiny_vault), store.root)
    idx = ProvenanceIndex(vault)
    f_old = idx.facts(f"{PREFIX}/{store.get(old).file}")
    f_new = idx.facts(f"{PREFIX}/{store.get(new).file}")
    assert f_old.is_historical is True
    assert f_new.is_historical is False          # `supersedes` marks the CURRENT note: not historical
    assert idx.marker(f"{PREFIX}/{store.get(old).file}") == "[histórico]"


def test_search_puts_current_saved_note_above_superseded(tiny_vault, tmp_path, store):
    old = store.save("Config zephyrquux", "A configuração zephyrquux usa valor ANTIGO zephyrquux zephyrquux.")
    new = store.save("Config zephyrquux revisada", "A configuração vigente zephyrquux usa valor NOVO.", supersedes=old)
    gw = _gateway(tiny_vault, tmp_path, store)
    r = gw.search("configuração zephyrquux", "baseline", 5, persist=False)
    files = [s.file for s in r.sources]
    assert files and files[0].endswith(f"{new}.md")
    if any(f.endswith(f"{old}.md") for f in files):         # demoted, never above the current one
        assert [i for i, f in enumerate(files) if f.endswith(f"{old}.md")][0] > 0


# ===== ANA-148: duplicates / contradictions =====
def test_100_repeated_saves_leave_no_near_duplicates(store):
    base = "O pipeline de deploy roda testes, constrói a imagem e publica no registro interno às sextas."
    for i in range(100):
        lc.save_checked(store, "Deploy", base + (" " * (i % 3)), dedupe="skip")
    rep = lc.audit(store)
    assert rep["total"] == 1 and rep["duplicates"] == 0 and rep["duplicate_rate"] == 0.0


def test_warn_mode_reports_similar_and_suggests_action(store):
    a = lc.save_checked(store, "Cache", "O cache usa Redis versão 7 na porta 6379.", dedupe="warn")
    assert a["saved"] and a["similar"] == [] and a["action"] == "none"
    b = lc.save_checked(store, "Cache", "O cache usa Redis versão 7 na porta 6379.", dedupe="warn")
    assert b["saved"] and b["similar"][0]["id"] == a["id"] and b["similar"][0]["reason"] == "near_duplicate"
    assert b["action"] == "suggest_update"


def test_contradiction_is_flagged_and_supersede_suggested(store):
    a = lc.save_checked(store, "Porta do painel", "A porta do painel é 8000 desde 2026-01-10.")
    b = lc.save_checked(store, "Porta do painel", "A porta do painel é 9000 desde 2026-09-10.")
    assert b["similar"][0]["reason"] == "possible_contradiction" and b["action"] == "supersede"
    assert b["id"] != a["id"]


def test_explicit_supersedes_marks_old_without_deleting(store):
    a = store.save("Regra", "valor 1")
    b = lc.save_checked(store, "Regra", "valor 2", supersedes=a)
    assert store.get(a).status == "superseded" and store.get(a).superseded_by == b["id"]
    assert (store.root / store.get(a).file).exists()


def test_dedupe_update_mode_updates_in_place_with_history(store):
    a = lc.save_checked(store, "Nota", "mesmo conteudo exato para a nota", dedupe="update")
    b = lc.save_checked(store, "Nota", "mesmo conteudo exato para a nota", dedupe="update")
    assert b["updated"] is True and b["id"] == a["id"] and lc.audit(store)["total"] == 1


def test_dedupe_off_restores_old_behaviour(store):
    for _ in range(3):
        r = lc.save_checked(store, "X", "conteudo repetido igual", dedupe="off")
        assert r["saved"] and r["similar"] == []
    assert lc.audit(store)["total"] == 3
    with pytest.raises(InvalidNote):
        lc.save_checked(store, "X", "c", dedupe="banana")


# ===== ANA-150: versioning, rollback, soft delete =====
def test_update_keeps_history_and_rollback_restores_identical_bytes(store):
    nid = store.save("Doc", "versão um do texto", ["a"])
    p = store._path_for(nid)
    bytes_v1 = p.read_bytes()
    sha_v1 = hashlib.sha256(bytes_v1).hexdigest()
    store.update(nid, content="versão dois do texto", tags=["a", "b"])
    store.update(nid, content="versão três do texto")
    hist = lc.history(store, nid)
    assert len(hist) == 2 and hist[0]["sha256"] == sha_v1
    assert "versão três" in store.get(nid).content
    d = lc.diff(store, nid, hist[0]["version"])
    assert "-versão um do texto" in d and "+versão três do texto" in d
    lc.rollback(store, nid, hist[0]["version"])
    assert hashlib.sha256(store._path_for(nid).read_bytes()).hexdigest() == sha_v1   # byte-identical
    assert len(lc.history(store, nid)) == 3                                          # rollback is reversible
    assert store.get(nid).integrity_ok() is True


def test_update_validates_and_refuses_secrets(store):
    nid = store.save("Doc", "texto")
    with pytest.raises(SavedContextError):
        store.update(nid, content="chave sk-abcdefghijklmnopqrstuvwxyz0123456789")
    assert store.get(nid).content == "texto"
    with pytest.raises(NoteNotFound):
        store.update("0123456789", content="x")


def test_version_param_cannot_escape_history_dir(store):
    nid = store.save("Doc", "texto")
    for bad in ("../../x", "..\\x", "1/../2", "abc", ""):
        with pytest.raises((InvalidNote, NoteNotFound)):
            lc.diff(store, nid, bad)


def test_delete_is_soft_and_restorable(store):
    nid = store.save("Doc", "texto a apagar")
    store.delete(nid)
    with pytest.raises(NoteNotFound):
        store.get(nid)
    items = lc.trash_list(store)
    assert len(items) == 1 and items[0]["id"] == nid
    assert lc.restore(store, items[0]["trash_id"]) == nid
    assert store.get(nid).content == "texto a apagar" and lc.trash_list(store) == []


def test_restore_rejects_path_traversal(store):
    store.save("Doc", "x")
    for bad in ("../../etc__abcdef0123.md", "..\\x", "nao-existe"):
        with pytest.raises(SavedContextError):
            lc.restore(store, bad)


def test_hard_delete_flag(store, monkeypatch):
    monkeypatch.setenv("MG_MEMORY_SOFT_DELETE", "0")
    nid = store.save("Doc", "x")
    store.delete(nid)
    assert lc.trash_list(store) == []


def test_forget_all_leaves_a_restorable_backup_zip(store):
    store.save("A", "um")
    store.save("B", "dois")
    assert store.forget_all(confirm=True) == 2
    zips = list((store.state_dir / "backups").glob("forget-*.zip"))
    assert len(zips) == 1
    import zipfile
    assert len(zipfile.ZipFile(zips[0]).namelist()) == 2


def test_state_dir_is_outside_the_mounted_notes_folder(store):
    store.save("A", "um")
    store.update(store.list()[0].id, content="dois")
    store.delete(store.list()[0].id)
    assert all(p.is_file() and p.suffix == ".md" for p in store.root.iterdir()) if store.root.exists() else True
    assert store.root not in store.state_dir.parents and store.state_dir != store.root
    assert (store.state_dir / "history").is_dir() and (store.state_dir / "trash").is_dir()


# ===== ANA-157: TTL =====
def test_expired_note_never_in_default_topk_and_flagged_in_listing(tiny_vault, tmp_path, store):
    exp = store.save("Temporário", "O código quasarwhisk expira logo.", expires_at="2020-01-01")
    store.save("Permanente", "O código quasarwhisk é o definitivo.")
    n = store.get(exp)
    assert n.is_expired() and n.to_dict()["expired"] is True
    listed = store.list()
    assert listed[-1].id == exp                                  # demoted to the end
    assert exp not in [x.id for x in store.list(include_expired=False)]
    gw = _gateway(tiny_vault, tmp_path, store)
    files = [s.file for s in gw.search("código quasarwhisk", "baseline", 5, persist=False).sources]
    assert files and not any(f.endswith(f"{exp}.md") for f in files)


def test_expired_note_comes_back_for_a_history_query(tiny_vault, tmp_path, store):
    exp = store.save("Temporário", "O código quasarwhisk expira logo.", expires_at="2020-01-01")
    gw = _gateway(tiny_vault, tmp_path, store)
    r = gw.search("histórico anterior do código quasarwhisk", "baseline", 5, persist=False)
    assert any(s.file.endswith(f"{exp}.md") for s in r.sources)


def test_reap_dry_run_then_apply(store):
    exp = store.save("Velha", "vai expirar", expires_at="2020-01-01")
    keep = store.save("Nova", "fica", ttl_days=10)
    dry = lc.reap(store, dry_run=True)
    assert [e["id"] for e in dry["expired"]] == [exp] and dry["moved"] == 0 and store.get(exp)
    real = lc.reap(store, dry_run=False)
    assert real["moved"] == 1
    with pytest.raises(NoteNotFound):
        store.get(exp)
    assert store.get(keep) and len(lc.trash_list(store)) == 1
    assert lc.audit(store)["trash"] == 1


def test_trash_is_purged_after_ttl(store, monkeypatch):
    nid = store.save("A", "x")
    store.delete(nid)
    monkeypatch.setenv("MG_MEMORY_TRASH_DAYS", "1")
    future = datetime.now(timezone.utc) + timedelta(days=2)
    rep = lc.reap(store, dry_run=False, now=future)
    assert rep["purged"] == 1 and lc.trash_list(store) == []


def test_audit_counts_expired(store):
    store.save("A", "x", expires_at="2020-01-01")
    store.save("B", "y")
    assert lc.audit(store)["expired"] == 1


# ===== ANA-158 / ANA-160: feedback =====
def test_feedback_counts_and_two_wrongs_exclude_from_default_search(tiny_vault, tmp_path, store):
    nid = store.save("Info", "A senha do wifi vermelhoturquesa mudou.", confidence=0.9)
    store.save("Outra", "A informação vermelhoturquesa correta é outra.")
    lc.feedback(store, nid, "useful", author="gabriel")
    r1 = lc.feedback(store, nid, "wrong", "dado errado", author="gabriel")
    assert r1["excluded_from_default_search"] is False
    r2 = lc.feedback(store, nid, "wrong", "continua errado", author="hermes")
    assert r2["excluded_from_default_search"] is True and r2["feedback_wrong"] == 2
    assert r2["confidence"] < 0.9
    gw = _gateway(tiny_vault, tmp_path, store)
    files = [s.file for s in gw.search("vermelhoturquesa", "baseline", 5, persist=False).sources]
    assert not any(f.endswith(f"{nid}.md") for f in files) and files


def test_feedback_does_not_invent_confidence_and_keeps_updated(store):
    nid = store.save("A", "x")
    before = store.get(nid).updated
    lc.feedback(store, nid, "stale", author="a")
    n = store.get(nid)
    assert n.confidence is None and n.updated == before and n.feedback_stale == 1


def test_feedback_validation(store):
    nid = store.save("A", "x")
    for bad in ("", "otimo", None):
        with pytest.raises(InvalidNote):
            lc.feedback(store, nid, bad)
    with pytest.raises(InvalidNote):
        lc.feedback(store, nid, "wrong", "linha1\nlinha2")
    with pytest.raises(InvalidNote):
        lc.feedback(store, nid, "wrong", "sk-abcdefghijklmnopqrstuvwxyz0123456789")
    with pytest.raises(NoteNotFound):
        lc.feedback(store, "0123456789", "wrong")


def test_usefulness_report(store):
    a, b = store.save("A", "um"), store.save("B", "dois")
    lc.feedback(store, a, "useful", author="x")
    lc.feedback(store, a, "useful", author="x")
    lc.feedback(store, b, "wrong", author="x")
    rep = lc.usefulness(store)
    assert [r["id"] for r in rep] == [a, b] and rep[0]["net"] == 2 and rep[1]["net"] == -1


def test_feedback_without_author_or_review_never_enters_calibration(store):
    nid = store.save("A", "x")
    lc.feedback(store, nid, "wrong")                       # anonymous
    lc.feedback(store, nid, "wrong", author="gabriel")     # named, not reviewed
    lc.feedback(store, nid, "useful", author="hermes")
    assert lc.calibration_events(store) == []              # 0 labels without origin/review
    lc.review_feedback(store, 0, "gabriel")                # reviewed but anonymous author -> still out
    assert lc.calibration_events(store) == []
    lc.review_feedback(store, 1, "gabriel")
    cal = lc.calibration_events(store)
    assert len(cal) == 1 and cal[0]["author"] == "gabriel" and cal[0]["reviewed_by"] == "gabriel"
    with pytest.raises(NoteNotFound):
        lc.review_feedback(store, 99, "x")


def test_grounding_failure_is_an_automatic_weak_signal(store):
    nid = store.save("A", "x")
    f = store.get(nid).file
    n = lc.record_grounding_failure(store, [{"file": f"saved_context/{f}"}, {"file": "10-Trabalho/vault.md"}], run_id="r1")
    assert n == 1 and store.get(nid).feedback_stale == 1
    ev = lc.feedback_events(store)[0]
    assert ev["source"] == "auto" and ev["reviewed"] is False and ev["author"] == "system:grounding"
    assert lc.calibration_events(store) == []


# ===== ANA-156 / 162 =====
def test_consolidate_proposes_then_applies_without_deleting(store):
    base = "O processo de release valida changelog, tag e artefato antes de publicar o pacote."
    ids = [store.save("Release", base + " " * i) for i in range(3)]
    store.save("Outro", "algo completamente diferente sobre férias de dezembro")
    plan = lc.consolidate(store, apply=False)
    assert len(plan["groups"]) == 1 and len(plan["groups"][0]["supersede"]) == 2 and plan["superseded"] == 0
    assert lc.audit(store)["duplicates"] == 2
    done = lc.consolidate(store, apply=True)
    assert done["superseded"] == 2
    rep = lc.audit(store)
    assert rep["total"] == 4 and rep["active"] == 2 and rep["duplicates"] == 0 and rep["by_status"]["superseded"] == 2


def test_migrate_v1_to_v2_with_backup(store, monkeypatch):
    monkeypatch.setenv("MG_MEMORY_SCHEMA_V2", "0")
    ids = [store.save(f"V1 {i}", f"corpo antigo {i}") for i in range(3)]
    monkeypatch.delenv("MG_MEMORY_SCHEMA_V2")
    assert lc.audit(store)["schema_v1"] == 3
    dry = lc.migrate_v1(store, dry_run=True)
    assert len(dry["candidates"]) == 3 and dry["migrated"] == 0 and lc.audit(store)["schema_v1"] == 3
    real = lc.migrate_v1(store, dry_run=False)
    assert real["migrated"] == 3 and os.path.exists(real["backup"])
    a = lc.audit(store)
    assert a["schema_v1"] == 0 and a["schema_v2"] == 3 and a["integrity_failures"] == []
    n = store.get(ids[0])
    assert n.content == "corpo antigo 0" and n.created  # content and created untouched


def test_contradiction_candidates_are_for_review_not_verdicts(store):
    store.save("Limite de requisições", "O limite de requisições é 100 por minuto desde 2026-01-05.")
    store.save("Limite de requisições", "O limite de requisições é 500 por minuto desde 2026-08-05.")
    store.save("Receita de bolo", "Misture farinha, ovos e açúcar e asse por 40 minutos.")
    cands = lc.contradictions(store)
    assert len(cands) == 1 and cands[0]["needs_human_review"] is True and cands[0]["verdict"] is None
    assert "100" in cands[0]["only_a"] + cands[0]["only_b"]


# ===== ANA-163: JSONL =====
def test_export_import_roundtrip_preserves_every_field(store, tmp_path):
    a = store.save("A", "corpo a", ["x", "y"], "proj", "hermes", kind="fact", ttl_days=5, confidence=0.4, source="url:http://e")
    b = store.save("B", "corpo b", supersedes=a)
    lc.feedback(store, a, "useful", author="g")
    lc.feedback(store, b, "stale", author="g")
    dump = lc.export_jsonl(store)
    fresh = SavedContextStore(tmp_path / "other" / "saved_context", rate_per_min=1000)
    res = lc.import_jsonl(fresh, dump)
    assert res == {"imported": 2, "skipped": 0, "count": 2}
    for nid in (a, b):
        assert store.get(nid) == fresh.get(nid)                           # 100% of fields
        assert (store.root / store.get(nid).file).read_bytes() == (fresh.root / fresh.get(nid).file).read_bytes()
    assert lc.export_jsonl(fresh) == dump                                 # idempotent
    assert lc.import_jsonl(fresh, dump)["skipped"] == 2                   # no silent overwrite


def test_import_rejects_corruption_before_writing(store, tmp_path):
    store.save("A", "corpo a")
    store.save("B", "corpo b")
    dump = lc.export_jsonl(store)
    lines = dump.splitlines()
    fresh = SavedContextStore(tmp_path / "o" / "saved_context", rate_per_min=1000)
    bad_checksum = "\n".join([lines[0]] + [ln.replace("corpo ", "corpo X") for ln in lines[1:]]) + "\n"
    assert bad_checksum != dump
    bad_count = "\n".join([lines[0], lines[1]]) + "\n"
    bad_format = lines[0].replace("anamnesia-memory/1", "outro/9") + "\n" + "\n".join(lines[1:]) + "\n"
    for bad in (bad_checksum, bad_count, bad_format, "", "não é json\n"):
        with pytest.raises(InvalidNote):
            lc.import_jsonl(fresh, bad)
    assert not fresh.root.exists() or not list(fresh.root.iterdir())


def test_import_rejects_path_traversal_and_bad_ids(store, tmp_path):
    store.save("A", "corpo a")
    rec = json.loads(lc.export_jsonl(store).splitlines()[1])
    fresh = SavedContextStore(tmp_path / "o" / "saved_context", rate_per_min=1000)
    for field, val in (("file", "../../evil.md"), ("id", "../../../x"), ("file", "C:\\evil.md")):
        r = dict(rec, **{field: val})
        body = json.dumps(r, ensure_ascii=False, sort_keys=True)
        head = json.dumps({"format": "anamnesia-memory/1", "count": 1, "sha256": hashlib.sha256(body.encode()).hexdigest()})
        with pytest.raises(SavedContextError):
            lc.import_jsonl(fresh, head + "\n" + body + "\n")
    assert not (tmp_path / "evil.md").exists()


def test_import_rejects_tampered_content_hash(store, tmp_path):
    store.save("A", "corpo a")
    rec = json.loads(lc.export_jsonl(store).splitlines()[1])
    rec["content"] = "adulterado"
    body = json.dumps(rec, ensure_ascii=False, sort_keys=True)
    head = json.dumps({"format": "anamnesia-memory/1", "count": 1, "sha256": hashlib.sha256(body.encode()).hexdigest()})
    with pytest.raises(InvalidNote, match="content_sha256"):
        lc.import_jsonl(SavedContextStore(tmp_path / "o" / "saved_context", rate_per_min=1000), head + "\n" + body + "\n")


# ===== ANA-147 / 149 / 152 / 153 =====
def test_context_pack_contract_and_verification(tiny_vault, tmp_path, store, monkeypatch):
    from app.services import context_pack as cp
    monkeypatch.setattr(cp, "packs_dir", lambda: tmp_path / "packs")
    gw = _gateway(tiny_vault, tmp_path, store)
    r = gw.search("stack backend FastAPI", "baseline", 5, context_budget=900, persist=False)
    pack = cp.build_pack(gw, r, scope=None, token_budget=900)
    assert pack["id"] and pack["pack_version"] == 1 and pack["token_budget"] == 900
    assert pack["sources"] and all(s["sha256"] and len(s["sha256"]) == 64 and s["why"] for s in pack["sources"])
    assert pack["context_tokens"] <= 900
    pid = cp.save_pack(pack)
    loaded = cp.load_pack(pid)
    assert loaded == json.loads(json.dumps(pack))
    assert cp.verify_pack(gw, loaded)["ok"] is True
    target = tiny_vault / loaded["sources"][0]["path"]
    target.write_text(target.read_text(encoding="utf-8") + "\nlinha nova\n", encoding="utf-8")
    v = cp.verify_pack(gw, loaded)
    assert v["ok"] is False and loaded["sources"][0]["path"] in v["changed"]
    assert cp.is_expired(dict(loaded, created_at=time.time() - 10**6)) is True
    with pytest.raises(ValueError):
        cp.load_pack("../../etc/passwd")
    assert cp.load_pack("0" * 12) is None


def test_pack_does_not_store_note_text(tiny_vault, tmp_path, store, monkeypatch):
    from app.services import context_pack as cp
    monkeypatch.setattr(cp, "packs_dir", lambda: tmp_path / "packs")
    gw = _gateway(tiny_vault, tmp_path, store)
    r = gw.search("stack backend FastAPI", "baseline", 5, persist=False)
    raw = json.dumps(cp.build_pack(gw, r))
    assert r.sources and all(len(s.file) < 200 for s in r.sources)
    assert (tiny_vault / r.sources[0].file).read_text(encoding="utf-8").strip()[:80] not in raw


def test_every_delivered_block_has_a_nonempty_why(tiny_vault, tmp_path, store):
    gw = _gateway(tiny_vault, tmp_path, store)
    for q in ("stack backend FastAPI", "viagem praia dezembro", "orçamento hotel"):
        r = gw.search(q, "baseline", 5, persist=False)
        assert r.sources and all(s.why.strip() and "canal=" in s.why and "score=" in s.why for s in r.sources)
        assert all("why" in d for d in r.to_dict()["sources"])


def test_why_is_persisted_in_the_run_and_one_sql_query_lists_evidence(tiny_vault, tmp_path, store):
    gw = _gateway(tiny_vault, tmp_path, store)
    r = gw.search("stack backend FastAPI", "baseline", 5)
    rows = gw.db.run_evidence(r.run_id)                      # ONE sql statement
    assert [x["file"] for x in rows] == [s.file for s in r.sources]
    assert all(x["why"] for x in rows) and rows[0]["query"] == "stack backend FastAPI"
    rev = gw.db.runs_for_note(rows[0]["file"])
    assert rev and rev[0]["run_id"] == r.run_id


def test_quality_signals_are_side_by_side_without_composite(tiny_vault, tmp_path, store):
    from app.services import context_pack as cp
    gw = _gateway(tiny_vault, tmp_path, store)
    r = gw.search("stack backend FastAPI", "baseline", 5, persist=False)
    q = cp.quality_signals(gw, r)
    assert set(q) >= {"relevance", "redundancy", "freshness_stale_share", "injection_flags", "tokens", "sources"}
    assert q["composite"] is None and q["relevance"] is None and 0.0 <= q["redundancy"] <= 1.0
    labelled = cp.quality_signals(gw, r, {r.sources[0].file: "relevant"})
    assert labelled["relevance"] and labelled["relevance"] > 0


# ===== ANA-161: compact provenance =====
def test_compact_provenance_is_about_one_token_per_source(vault_with_notes):
    from app.services.provenance import ProvenanceIndex, provenance_tokens
    idx = ProvenanceIndex(vault_with_notes)
    full = idx.line("30-Projetos/P/decisoes/a.md")
    compact = idx.compact_line("30-Projetos/P/decisoes/a.md", 1)
    assert compact.startswith("[1·") and "2026-09-01" in compact and len(compact) < len(full)
    assert provenance_tokens([compact]) < provenance_tokens([full])
    assert provenance_tokens([compact]) <= 12


@pytest.fixture
def vault_with_notes(tmp_path):
    root = tmp_path / "v"
    d = root / "30-Projetos" / "P" / "decisoes"
    d.mkdir(parents=True)
    (d / "a.md").write_text("---\nid: a\ntitle: Algo\ntype: decisao\nstatus: ativo\nprojeto: p\ncreated: 2026-09-01\n"
                            "updated: 2026-09-01\n---\n\n# Algo\n\ncorpo\n", encoding="utf-8")
    return ObsidianVault(root)


def test_provenance_mode_compact_is_opt_in(monkeypatch):
    from config.optimizer import OptimizerConfig
    assert OptimizerConfig().provenance_mode == "full" and OptimizerConfig().provenance is False
    monkeypatch.setenv("MG_OPT_PROVENANCE_MODE", "compact")
    assert OptimizerConfig().provenance_mode == "compact"


def test_compact_provenance_end_to_end(tiny_vault, tmp_path, store):
    gw = _gateway(tiny_vault, tmp_path, store)
    gw.optimizer.cfg = gw.optimizer.cfg.with_(provenance=True, provenance_mode="compact")
    gw.optimizer.cache.clear()
    r = gw.search("stack backend FastAPI", "baseline", 5, persist=False)
    assert "[1·" in r.context


# ===== ANA-159 =====
def test_context_plan_split_is_bounded_and_proportional():
    from app.services.context_plan import MIN_BUDGET, plan_for_run
    p = plan_for_run(["orchestrator", "researcher", "implementer", "reviewer"], 8000, project="anamnesia")
    assert sum(p.per_role.values()) <= 8000 and all(v >= MIN_BUDGET for v in p.per_role.values())
    assert p.for_role("researcher") > p.for_role("implementer") > p.for_role("reviewer") > p.for_role("orchestrator")
    assert p.for_role("papel-desconhecido") == min(p.per_role.values())
    tiny = plan_for_run(["researcher", "reviewer", "implementer"], 300)
    assert tiny.total_budget == 600 and tiny.notes and sum(tiny.per_role.values()) <= 600
    with pytest.raises(ValueError):
        plan_for_run([])
    assert plan_for_run(["researcher", "researcher"], 1000).per_role == {"researcher": 1000}


# ===== ANA-154/155/151 =====
def test_conflict_detector_precision_recall_on_heldout_split():
    from app.benchmark.memory_eval import evaluate_conflict_detector
    for split in ("train", "val"):
        r = evaluate_conflict_detector(split)
        assert r["n"] > 0
        for cls in ("duplicate", "contradiction"):
            assert r["classes"][cls]["precision"] == 1.0 and r["classes"][cls]["recall"] == 1.0, (split, r)


def test_temporal_arms_reduce_stale_version_delivery(tmp_path):
    from app.benchmark.memory_eval import temporal_arms, temporal_corpus
    from app.gateway.memory_gateway import MemoryGateway
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig
    root = tmp_path / "tv"
    qs = temporal_corpus(root, 8)
    gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=root, data_dir=tmp_path / "d"),
                       bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark", benchmark_mode=False))
    gw.warm()
    res = temporal_arms(gw, qs)
    a, c, d = res["A_off"], res["C_demote"], res["D_exclude"]
    assert a["current_in_context"] <= c["current_in_context"] and c["current_in_context"] == 1.0
    assert c["stale_on_top"] < a["stale_on_top"] and c["stale_on_top"] == 0.0     # error "old version" falls
    assert d["stale_delivered"] == 0.0 and d["current_in_context"] == 1.0


def test_budget_curve_is_monotone_and_respects_ceiling(tmp_path):
    from app.benchmark import golden
    from app.benchmark.memory_eval import budget_curve
    from app.gateway.memory_gateway import MemoryGateway
    synthetic = golden.ROOT / "data" / "synthetic_vault"
    if not synthetic.exists():
        pytest.skip("synthetic vault ausente")
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig
    gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=synthetic, data_dir=tmp_path / "d"),
                       bench_cfg=BenchmarkConfig(db_path=str(tmp_path / "b.db"), profile="benchmark", benchmark_mode=False))
    gw.warm()
    items = [i for i in golden.load(split="val") if i.get("answerable")][:20]
    rows = budget_curve(gw, items, [300, 900, 3000])
    assert [r["budget"] for r in rows] == [300, 900, 3000]
    assert rows[0]["mean_context_tokens"] <= rows[1]["mean_context_tokens"] <= rows[2]["mean_context_tokens"]
    assert all(r["mean_context_tokens"] <= r["budget"] * 1.05 for r in rows)


# ===== REST (ANA-078 + Onda 3 routes) =====
@pytest.fixture
def api(tmp_path, tiny_vault, monkeypatch):
    from app.api import routes
    from app.main import create_app
    from app.memory_store import store as store_mod
    st = SavedContextStore(tmp_path / "home" / "saved_context", rate_per_min=100000)
    monkeypatch.setattr(store_mod, "get_store", lambda: st)
    import app.api.memory_store as api_mod
    monkeypatch.setattr(api_mod, "get_store", lambda: st)
    gw = _gateway(tiny_vault, tmp_path, st)
    monkeypatch.setitem(routes._state, "gateway", gw)
    from app.services.security import get_or_create_local_token
    tok = get_or_create_local_token()
    c = TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    c.headers.update({"X-MG-Token": tok, "Origin": "http://127.0.0.1:8000"})
    return c, st


def test_router_mounted_and_openapi_has_all_memory_routes(api):
    c, _ = api
    paths = c.get("/openapi.json").json()["paths"]
    for p in ("/api/memory/notes", "/api/memory/notes/{note_id}", "/api/memory/notes/{note_id}/history",
              "/api/memory/notes/{note_id}/diff", "/api/memory/notes/{note_id}/rollback",
              "/api/memory/notes/{note_id}/feedback", "/api/memory/trash", "/api/memory/reap", "/api/memory/audit",
              "/api/memory/usefulness", "/api/memory/contradictions", "/api/memory/consolidate", "/api/memory/migrate",
              "/api/memory/export.jsonl", "/api/memory/import", "/api/memory/packs", "/api/memory/packs/{pack_id}/verify",
              "/api/memory/runs/{run_id}/evidence", "/api/memory/evidence"):
        assert p in paths, p


def test_rest_full_lifecycle(api):
    c, st = api
    r = c.post("/api/memory/notes", json={"title": "Porta", "content": "A porta do painel é 8000 desde 2026-01-10.",
                                          "kind": "fact", "ttl_days": 30, "confidence": 0.7})
    assert r.status_code == 201
    a = r.json()
    assert a["id"] and a["saved"] is True and a["similar"] == []
    b = c.post("/api/memory/notes", json={"title": "Porta", "content": "A porta do painel é 9000 desde 2026-09-10."}).json()
    assert b["action"] == "supersede" and b["similar"][0]["id"] == a["id"]
    assert c.post("/api/memory/notes", json={"title": "x", "content": "y", "kind": "banana"}).status_code == 422
    assert c.put(f"/api/memory/notes/{a['id']}", json={"content": "A porta do painel é 8080."}).status_code == 200
    hist = c.get(f"/api/memory/notes/{a['id']}/history").json()["versions"]
    assert len(hist) == 1
    d = c.get(f"/api/memory/notes/{a['id']}/diff", params={"a": hist[0]["version"]})
    assert d.status_code == 200 and "8080" in d.text
    assert c.post(f"/api/memory/notes/{a['id']}/rollback", json={"version": hist[0]["version"]}).status_code == 200
    assert "8000" in c.get(f"/api/memory/notes/{a['id']}").json()["content"]
    fb = c.post(f"/api/memory/notes/{a['id']}/feedback", json={"verdict": "wrong", "reason": "r", "author": "gabriel"})
    assert fb.status_code == 200 and fb.json()["feedback_wrong"] == 1
    assert c.post(f"/api/memory/notes/{a['id']}/feedback", json={"verdict": "meh"}).status_code == 422
    assert c.delete(f"/api/memory/notes/{b['id']}").status_code == 200
    tr = c.get("/api/memory/trash").json()["items"]
    assert len(tr) == 1 and c.post(f"/api/memory/trash/{tr[0]['trash_id']}/restore").json() == {"restored": b["id"]}
    aud = c.get("/api/memory/audit").json()
    assert aud["total"] == 2 and aud["integrity_failures"] == []
    assert c.get("/api/memory/contradictions").status_code == 200
    assert c.post("/api/memory/reap", json={}).json()["dry_run"] is True
    dump = c.get("/api/memory/export.jsonl")
    assert dump.status_code == 200 and dump.text.splitlines()[0].startswith('{"format": "anamnesia-memory/1"')
    st.forget_all(confirm=True)
    imp = c.post("/api/memory/import", content=dump.text.encode("utf-8"))
    assert imp.json()["imported"] == 2 and c.get("/api/memory/audit").json()["total"] == 2


def test_rest_write_routes_need_the_token(api):
    c, _ = api
    nid = c.post("/api/memory/notes", json={"title": "A", "content": "b"}).json()["id"]
    anon = TestClient(c.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    for method, url, body in (("put", f"/api/memory/notes/{nid}", {"content": "z"}),
                              ("post", f"/api/memory/notes/{nid}/feedback", {"verdict": "wrong"}),
                              ("post", f"/api/memory/notes/{nid}/rollback", {"version": "1"}),
                              ("post", "/api/memory/reap", {"dry_run": False}),
                              ("post", "/api/memory/consolidate", {"apply": True}),
                              ("post", "/api/memory/migrate", {"dry_run": False}),
                              ("get", "/api/memory/export.jsonl", None), ("post", "/api/memory/import", None)):
        r = getattr(anon, method)(url, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (url, r.status_code)


def test_rest_pack_evidence_and_why(api):
    c, _ = api
    pk = c.post("/api/memory/packs", json={"query": "stack backend FastAPI", "context_budget": 900})
    assert pk.status_code == 201, pk.text
    pid = pk.json()["pack_id"]
    assert pk.json()["context_tokens"] <= 900
    assert c.get(f"/api/memory/packs/{pid}/verify").json()["ok"] is True
    assert c.get("/api/memory/packs/zzzz").status_code == 422 and c.get("/api/memory/packs/" + "0" * 12).status_code == 404
    ev = c.get(f"/api/memory/runs/{pk.json()['run_id']}/evidence")
    assert ev.status_code == 200 and all(s["why"] for s in ev.json()["sources"])
    q = c.get(f"/api/memory/runs/{pk.json()['run_id']}/quality").json()
    assert q["composite"] is None and "redundancy" in q
    assert c.get("/api/memory/runs/naoexiste/evidence").status_code == 404


def test_saved_note_over_rest_is_searchable_immediately(api):
    c, _ = api
    c.post("/api/memory/notes", json={"title": "Segredo do canário", "content": "O codinome zirconiobravo identifica o canário."})
    from app.api import routes
    r = routes._state["gateway"].search("zirconiobravo", "baseline", 3, persist=False)
    assert r.sources and r.sources[0].file.startswith(f"{PREFIX}/")


# ===== MCP =====
def test_mcp_memory_save_dedupe_supersedes_and_feedback(monkeypatch, tmp_path, store):
    monkeypatch.setenv("MG_MCP_SAVE", "1")
    monkeypatch.delenv("MG_SCOPE", raising=False)
    import importlib
    import app.mcp.server as srv
    srv = importlib.reload(srv)
    import app.memory_store.store as st_mod
    monkeypatch.setattr(st_mod, "get_store", lambda: store)
    a = srv.memory_save("Regra", "A regra de retenção é 30 dias.", kind="decision", ttl_days=90)
    assert a["saved"] is True and store.get(a["id"]).kind == "decision" and store.get(a["id"]).trust == "untrusted"
    b = srv.memory_save("Regra", "A regra de retenção é 30 dias.", dedupe="skip")
    assert b["saved"] is False and b["id"] == a["id"] and b["action"] == "suggest_update"
    c = srv.memory_save("Regra", "A regra de retenção é 60 dias.", supersedes=a["id"])
    assert store.get(a["id"]).status == "superseded" and c["action"] == "supersede"
    fb = srv.memory_feedback(c["id"], "wrong", "teste", client="hermes")
    assert fb["feedback_wrong"] == 1 and lc.feedback_events(store)[-1]["author"] == "hermes"
    assert "error" in srv.memory_feedback("0123456789", "wrong")
    assert "error" in srv.memory_save("Bad", "x", kind="banana")


def test_mcp_search_budget_and_pack_are_opt_in(monkeypatch, tiny_vault, tmp_path, store):
    import app.mcp.server as srv
    from app.services import context_pack as cp
    monkeypatch.setattr(cp, "packs_dir", lambda: tmp_path / "packs")
    monkeypatch.setattr(srv, "_gateway", _gateway(tiny_vault, tmp_path, store))
    plain = srv.memory_search("stack backend FastAPI", pipeline="baseline")
    assert "pack_id" not in plain
    packed = srv.memory_search("stack backend FastAPI", pipeline="baseline", budget=500, pack=True)
    assert len(packed["pack_id"]) == 12 and cp.load_pack(packed["pack_id"])["token_budget"] == 500
    assert packed["metrics"].get("context_tokens", 0) <= 500


# ===== gaps closed in the Onda 3 review (ANA-162 precision, ANA-156/163 rollback of the migration) =====
def test_contradiction_precision_at_n_meets_target(tmp_path):
    from app.benchmark.memory_eval import contradiction_precision
    r = contradiction_precision(tmp_path)
    assert r["flagged"] > 0 and r["precision_at_n"] is not None
    assert r["precision_at_n"] >= 0.7, r          # ANA-162 SUCCESS_METRIC
    assert r["recall"] is not None and r["recall"] >= 0.7, r


def test_migration_rollback_restores_original_v1_bytes(store, monkeypatch):
    monkeypatch.setenv("MG_MEMORY_SCHEMA_V2", "0")
    ids = [store.save(f"V1 {i}", f"corpo antigo {i}") for i in range(3)]
    monkeypatch.delenv("MG_MEMORY_SCHEMA_V2")
    before = {i: (store.root / store.get(i).file).read_bytes() for i in ids}
    real = lc.migrate_v1(store, dry_run=False)
    assert real["migrated"] == 3
    assert any((store.root / store.get(i).file).read_bytes() != before[i] for i in ids)   # migration changed files
    res = lc.import_jsonl(store, open(real["backup"], encoding="utf-8").read(), overwrite=True)
    assert res["imported"] == 3
    after = {i: (store.root / store.get(i).file).read_bytes() for i in ids}
    assert after == before                                                                   # rollback: identical bytes
    assert lc.audit(store)["schema_v1"] == 3 and lc.audit(store)["integrity_failures"] == []


def test_lifecycle_operations_never_log_note_bodies(store, caplog):
    import logging
    marker = "CORPO-SECRETO-ZXQ-91827"
    with caplog.at_level(logging.DEBUG):
        nid = lc.save_checked(store, "Nota log", f"conteúdo {marker} numero 1")["id"]
        store.update(nid, content=f"novo {marker} 2")
        lc.feedback(store, nid, "wrong", marker, author="t")
        lc.audit(store)
        lc.reap(store, dry_run=True)
        lc.export_jsonl(store)
        lc.contradictions(store)
    assert marker not in caplog.text


def test_onda3_report_script_verdicts_all_pass():
    import importlib.util
    spec = importlib.util.spec_from_file_location("measure_onda3", os.path.join(os.path.dirname(__file__), "..", "scripts", "measure_onda3_memory.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    v = mod.verdicts(mod.measure())
    assert v and all(v.values()), [k for k, ok in v.items() if not ok]
