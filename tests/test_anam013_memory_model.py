"""ANAM-013: ciclo de vida, escopo/visibilidade, uso, decay e ranking composto do memory_store."""
from __future__ import annotations

import time

import pytest

from app.memory_store import model
from app.memory_store.store import InvalidNote, SavedContextStore, parse

DAY = 86400.0


@pytest.fixture()
def st(tmp_path):
    return SavedContextStore(tmp_path / "saved_context", rate_per_min=100000)


def _save(st, title="Nota", content="conteudo base", **kw):
    return st.save(title, content, **kw)


# -- estados / transições -----------------------------------------------------------------------
def test_state_vocabulary_and_table_cover_all_states():
    assert model.STATES == ("candidate", "active", "reinforced", "stale", "archived", "superseded", "deleted")
    assert set(model.TRANSITIONS) == set(model.STATES)
    for dsts in model.TRANSITIONS.values():
        assert dsts <= set(model.STATES)


@pytest.mark.parametrize("src,dst,ok", [
    ("candidate", "active", True), ("candidate", "reinforced", False), ("candidate", "archived", False),
    ("active", "reinforced", True), ("active", "stale", True), ("active", "candidate", False),
    ("reinforced", "stale", True), ("stale", "active", True), ("stale", "archived", True),
    ("archived", "active", True), ("archived", "stale", False), ("superseded", "active", True),
    ("deleted", "active", False), ("deleted", "archived", True), (None, "reinforced", True),
    ("active", "active", True)])
def test_validate_transition_table(src, dst, ok):
    if ok:
        assert model.validate_transition(src, dst) == dst
    else:
        with pytest.raises(model.InvalidTransition):
            model.validate_transition(src, dst)


def test_invalid_status_name_rejected():
    with pytest.raises(model.InvalidTransition):
        model.validate_transition("active", "banana")


def test_candidate_lifecycle_through_store(st):
    nid = _save(st, initial_status="candidate", trust="untrusted")
    assert st.get(nid).status == "candidate"
    model.transition(st, nid, "active", actor="humano", reason="revisado")
    model.transition(st, nid, "reinforced")
    model.transition(st, nid, "stale")
    model.transition(st, nid, "archived")
    assert st.get(nid).status == "archived"
    evs = model.events(st, nid)
    assert [e["to"] for e in evs] == ["active", "reinforced", "stale", "archived"]
    assert evs[0]["actor"] == "humano"
    with pytest.raises(model.InvalidTransition):
        model.transition(st, nid, "reinforced")
    assert st.get(nid).status == "archived"          # rejeitada: nada mudou


def test_quarantined_candidate_cannot_be_promoted(st):
    nid = _save(st, initial_status="candidate", trust="quarantined")
    with pytest.raises(model.InvalidTransition):
        model.transition(st, nid, "active")


def test_update_status_uses_transition_table(st):
    nid = _save(st)
    with pytest.raises(InvalidNote):
        st.update(nid, status="candidate")
    assert st.update(nid, status="stale").status == "stale"
    with pytest.raises(InvalidNote):
        st.update(nid, status="nonsense")


def test_reactivating_superseded_clears_both_sides(st):
    old = _save(st, "Porta", "A porta é 80")
    new = _save(st, "Porta", "A porta é 8080", supersedes=old)
    assert st.get(old).status == "superseded" and st.get(new).supersedes == old
    model.transition(st, old, "active", actor="humano")
    assert st.get(old).status == "active" and st.get(old).superseded_by is None
    assert st.get(new).supersedes is None


def test_deleted_is_tombstone_in_trash_and_restorable_only_to_archived(st):
    from app.memory_store import lifecycle
    nid = _save(st)
    model.transition(st, nid, "deleted", reason="lixo")
    assert not any(n.id == nid for n in st.list())
    tid = lifecycle.trash_list(st)[0]["trash_id"]
    lifecycle.restore(st, tid)
    assert st.get(nid).status == "deleted"
    with pytest.raises(model.InvalidTransition):
        model.transition(st, nid, "active")
    model.transition(st, nid, "archived")
    assert st.get(nid).status == "archived"


def test_transition_reason_rejects_secret_and_multiline(st):
    nid = _save(st)
    with pytest.raises(InvalidNote):
        model.transition(st, nid, "stale", reason="a\nb")
    with pytest.raises(InvalidNote):
        model.transition(st, nid, "stale", reason="sk-" + "a1B2c3D4" * 4)


# -- compatibilidade / migração suave -----------------------------------------------------------
V1 = ("---\nid: 0123456789\ntitle: \"Antiga\"\ntype: contexto-salvo\nproject: null\ntags: []\nsource_agent: null\n"
      "created: \"2026-01-01T00:00:00+00:00\"\nupdated: \"2026-01-01T00:00:00+00:00\"\n---\n# Antiga\n\ncorpo\n")


def test_v1_note_defaults_and_roundtrip_byte_identical(st):
    from app.memory_store.store import render
    n = parse(V1, "antiga-0123456789.md")
    assert n.scope is None and n.owner is None and n.importance is None
    assert render(n) == V1
    assert model.effective_scope(n) == {"scope": "global", "scope_id": None, "visibility": "shared", "owner": None}
    assert model.normalize_status(n.status) == "active"


def test_v2_note_without_new_fields_renders_unchanged(st):
    nid = _save(st, kind="fact")
    raw = (st.root / st.get(nid).file).read_text(encoding="utf-8")
    for k in ("scope:", "scope_id:", "visibility:", "owner:", "importance:"):
        assert k not in raw


def test_transition_upgrades_v1_note(st):
    st.root.mkdir(parents=True)
    (st.root / "antiga-0123456789.md").write_text(V1, encoding="utf-8", newline="\n")
    n = model.transition(st, "0123456789", "stale")
    assert n.schema == 2 and n.status == "stale" and n.content_sha256 and n.integrity_ok()


def test_scope_fields_persist_and_roundtrip(st):
    nid = _save(st, project="alfa", scope="session", scope_id="s-1", visibility="private", owner="hermes",
                importance=0.8)
    n = st.get(nid)
    assert (n.scope, n.scope_id, n.visibility, n.owner, n.importance) == ("session", "s-1", "private", "hermes", 0.8)
    assert st.list()[0].owner == "hermes"


@pytest.mark.parametrize("kw", [dict(scope="galaxy"), dict(scope="task"), dict(visibility="secret"),
                                dict(importance=1.5), dict(importance="x"), dict(initial_status="archived"),
                                dict(scope_id="x")])
def test_invalid_model_fields_rejected(st, kw):
    with pytest.raises(InvalidNote):
        _save(st, **kw)


def test_set_scope_does_not_bump_updated_and_is_versioned(st):
    nid = _save(st, project="alfa")
    before = st.get(nid).updated
    model.set_scope(st, nid, scope="global", visibility="private", owner="a1")
    n = st.get(nid)
    assert n.scope == "global" and n.updated == before
    assert st._history_dir(nid).is_dir() and any(st._history_dir(nid).iterdir())


# -- escopo / isolamento ------------------------------------------------------------------------
def test_project_isolation(st):
    a = st.get(_save(st, "A", "texto a", project="alfa"))
    assert model.can_read(a, {"project": "alfa"})
    assert not model.can_read(a, {"project": "beta"})
    assert not model.can_read(a, {})
    assert model.can_read(a, None) and model.can_read(a, {"admin": True})


def test_private_only_owner_and_global_shared_for_all(st):
    p = st.get(_save(st, "P", "x privado", visibility="private", owner="hermes"))
    assert model.can_read(p, {"agent": "hermes"}) and not model.can_read(p, {"agent": "codex"})
    noowner = st.get(_save(st, "Q", "y privado", visibility="private"))
    assert not model.can_read(noowner, {"agent": "codex"})
    g = st.get(_save(st, "G", "z global"))
    assert model.can_read(g, {"agent": "qualquer"})


def test_agent_session_task_scopes(st):
    s = st.get(_save(st, "S", "sessao", scope="session", scope_id="s1"))
    assert model.can_read(s, {"session": "s1"}) and not model.can_read(s, {"session": "s2"})
    t = st.get(_save(st, "T", "tarefa", scope="task", scope_id="t1"))
    assert model.can_read(t, {"task": "t1"}) and not model.can_read(t, {"project": "t1"})
    a = st.get(_save(st, "AG", "agente", scope="agent", scope_id="hermes"))
    assert model.can_read(a, {"agent": "hermes"}) and not model.can_read(a, {"agent": "codex"})


# -- uso ----------------------------------------------------------------------------------------
def test_usage_sidecar_counts_and_does_not_touch_markdown(st):
    nid = _save(st)
    path = st.root / st.get(nid).file
    raw = path.read_bytes()
    assert model.record_usage(st, [nid, nid, "naoexiste00"], run_id="r1", now=1000.0) == 2  # dedup de ids
    model.record_usage(st, [nid], cited=True, now=2000.0)
    u = model.usage_of(st, nid, now=2000.0)
    assert u["usage_count"] == 2 and u["cited_count"] == 1 and u["last_used"] == 2000.0
    assert path.read_bytes() == raw
    assert model.usage_of(st, "ffffffffff")["usage_count"] == 0


def test_usage_window_excludes_old(st):
    nid = _save(st)
    now = time.time()
    model.record_usage(st, [nid], now=now - 200 * DAY)
    model.record_usage(st, [nid], now=now - 1 * DAY)
    u = model.usage_of(st, nid, now=now)
    assert u["usage_count"] == 2 and u["usage_count_window"] == 1


# -- decay --------------------------------------------------------------------------------------
def _age(st, nid, days):
    """Envelhece a nota (campo updated) sem passar por _mutate."""
    from datetime import datetime, timedelta, timezone
    p = st.root / st.get(nid).file
    n = parse(p.read_text(encoding="utf-8"), p.name)
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    txt = p.read_text(encoding="utf-8").replace(f'updated: "{n.updated}"', f'updated: "{ts}"').replace(
        f'created: "{n.created}"', f'created: "{ts}"')
    p.write_text(txt, encoding="utf-8", newline="\n")


def test_recency_half_life_by_kind():
    class N:
        updated = created = None
        kind = "episodic"
    from datetime import datetime, timedelta, timezone
    N.updated = N.created = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    assert model.recency(N, now=time.time()) == pytest.approx(0.5, abs=0.01)
    N.kind = "preference"
    assert model.recency(N, now=time.time()) > 0.9


def test_decay_proposes_stale_dry_run_then_applies_never_deletes(st):
    old = _save(st, "Velha", "episodio velho", kind="episodic")
    fresh = _save(st, "Nova", "episodio novo", kind="episodic")
    _age(st, old, 120)
    rep = model.apply_decay(st)                       # dry-run
    assert rep["dry_run"] and rep["to_stale"] == [old] and st.get(old).status == "active"
    rep = model.apply_decay(st, dry_run=False)
    assert rep["applied"] == 1 and st.get(old).status == "stale" and st.get(fresh).status == "active"
    assert len(st.list()) == 2                        # nada apagado


def test_recent_use_prevents_stale(st):
    old = _save(st, "Velha", "episodio velho", kind="episodic")
    _age(st, old, 120)
    model.record_usage(st, [old], now=time.time() - 2 * DAY)
    assert model.decay_plan(st)["to_stale"] == []


def test_decay_archives_stale_but_never_decisions_or_pinned(st):
    a = _save(st, "A", "episodio a", kind="episodic")
    d = _save(st, "D", "decisao importante", kind="decision")
    pin = _save(st, "P", "fixada", kind="episodic", tags=["pinned"])
    for n in (a, d, pin):
        model.transition(st, n, "stale")
        _age(st, n, 400)
    plan = model.decay_plan(st)
    assert plan["to_archived"] == [a]


def test_reinforce_by_cited_usage_or_feedback(st):
    from app.memory_store import lifecycle
    a = _save(st, "A", "texto a")
    b = _save(st, "B", "texto b")
    now = time.time()
    for i in range(3):
        model.record_usage(st, [a], cited=True, now=now - i * DAY)
    lifecycle.feedback(st, b, "useful", author="u1")
    lifecycle.feedback(st, b, "useful", author="u2")
    plan = model.decay_plan(st, now=now)
    assert set(plan["to_reinforced"]) == {a, b}
    model.apply_decay(st, dry_run=False, now=now)
    assert st.get(a).status == "reinforced"


# -- ranking ------------------------------------------------------------------------------------
def test_hard_exclusions_always_apply(st):
    ids = {}
    for s in ("candidate", "archived", "stale", "reinforced"):
        ids[s] = _save(st, s, f"nota {s}", initial_status="candidate" if s == "candidate" else None)
    model.transition(st, ids["archived"], "archived")
    model.transition(st, ids["stale"], "stale")
    model.transition(st, ids["reinforced"], "reinforced")
    wrong = _save(st, "wrong", "errada")
    from app.memory_store import lifecycle
    lifecycle.feedback(st, wrong, "wrong", author="a")
    lifecycle.feedback(st, wrong, "wrong", author="b")
    quar = _save(st, "q", "quarentena", trust="quarantined")
    exp = _save(st, "e", "expirada", expires_at="2020-01-01")
    cands = [(i, 0.9) for i in [*ids.values(), wrong, quar, exp]]
    for mode in ("v1", "v2"):
        got = {r["id"] for r in model.rank_notes(st, cands, mode=mode)}
        # `stale` não é exclusão dura: continua rankeável (recência baixa a rebaixa)
        assert got >= {ids["reinforced"]} and not (got & {ids["candidate"], ids["archived"], wrong, quar, exp})


def test_rank_v1_is_pure_relevance_order(st):
    a, b = _save(st, "A", "a"), _save(st, "B", "b")
    got = model.rank_notes(st, [(a, 0.2), (b, 0.8)], mode="v1")
    assert [r["id"] for r in got] == [b, a] and got[0]["rank_mode"] == "v1"


def test_rank_default_mode_is_v1_and_env_flag(monkeypatch):
    monkeypatch.delenv("MG_MEMORY_RANK", raising=False)
    assert model.rank_mode() == "v1"
    monkeypatch.setenv("MG_MEMORY_RANK", "v2")
    assert model.rank_mode() == "v2"
    monkeypatch.setenv("MG_MEMORY_RANK", "lixo")
    assert model.rank_mode() == "v1"


def test_rank_v2_prefers_recent_used_confident_over_stale_equal_relevance(st):
    new = _save(st, "Nova", "nova", kind="episodic", confidence=0.95, importance=0.9)
    old = _save(st, "Velha", "velha", kind="episodic", confidence=0.2)
    _age(st, old, 60)
    now = time.time()
    for i in range(4):
        model.record_usage(st, [new], now=now - i * DAY)
    got = model.rank_notes(st, [(old, 0.8), (new, 0.8)], mode="v2", now=now)
    assert [r["id"] for r in got] == [new, old]
    bd = got[0]["breakdown"]
    assert {"relevance", "recency", "usage", "confidence", "importance", "trust_mult", "scope_mult"} <= set(bd)


def test_rank_v2_relevance_still_dominates_zero_and_untrusted_penalised(st):
    a = _save(st, "A", "a", trust="untrusted")
    b = _save(st, "B", "b")
    got = model.rank_notes(st, [(a, 0.8), (b, 0.8)], mode="v2")
    assert got[0]["id"] == b
    assert model.rank_notes(st, [(b, 0.0)], mode="v2")[0]["score"] == 0.0


def test_missing_confidence_is_neutral_not_rewarded(st):
    a = _save(st, "A", "a")
    b = _save(st, "B", "b", confidence=0.5)
    ra, rb = (model.rank_notes(st, [(i, 0.5)], mode="v2")[0] for i in (a, b))
    assert ra["breakdown"]["confidence"] == rb["breakdown"]["confidence"] == 0.5


def test_rank_respects_viewer_isolation(st):
    a = _save(st, "A", "a", project="alfa")
    b = _save(st, "B", "b", project="beta")
    got = model.rank_notes(st, [(a, 0.5), (b, 0.5)], viewer={"project": "alfa"}, mode="v2")
    assert [r["id"] for r in got] == [a]
    assert model.rank_notes(st, [("ffffffffff", 0.5)], mode="v2") == []


def test_scope_multiplier_orders_project_over_global(st):
    p = _save(st, "P", "p", project="alfa")
    g = _save(st, "G", "g")
    got = model.rank_notes(st, [(g, 0.5), (p, 0.5)], mode="v2")
    assert got[0]["id"] == p


# -- integração com lifecycle / jsonl -----------------------------------------------------------
def test_export_import_roundtrip_with_new_fields(st, tmp_path):
    from app.memory_store import lifecycle
    nid = _save(st, project="alfa", scope="project", visibility="private", owner="o1", importance=0.3)
    dump = lifecycle.export_jsonl(st)
    st2 = SavedContextStore(tmp_path / "other" / "saved_context", rate_per_min=1000)
    lifecycle.import_jsonl(st2, dump)
    n = st2.get(nid)
    assert (n.scope, n.visibility, n.owner, n.importance) == ("project", "private", "o1", 0.3)


def test_find_similar_counts_reinforced_but_not_candidate(st):
    from app.memory_store import lifecycle
    r = _save(st, "Porta do painel", "A porta do painel é 8080 sempre")
    model.transition(st, r, "reinforced")
    c = _save(st, "Porta cand", "A porta do painel é 8080 sempre", initial_status="candidate")
    hits = {h["id"] for h in lifecycle.find_similar(st, "Outra", "A porta do painel é 8080 sempre")}
    assert r in hits and c not in hits


def test_provenance_treats_candidate_and_deleted_as_historical():
    from app.services.provenance import HISTORICAL_STATUSES
    assert {"candidate", "deleted", "superseded", "archived"} <= HISTORICAL_STATUSES
