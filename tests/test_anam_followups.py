"""Follow-ups ANAM-013/033/034/041: privacidade no fluxo real, rank v2 atras da flag, Colibri key via env,
aviso JEV em loopback, ciclo local_ai. Sem rede, sem modelo real."""
from __future__ import annotations

import types

import pytest

from app.adapters.models.providers import GenerationResult
from app.memory_store import model
from app.memory_store.store import SavedContextStore
from app.routing import answer as ans
from app.routing.policy import preset
from app.routing.registry import ModelEntry, Price, Registry
from app.schemas.models import Candidate

GOOD = "Escolhemos Python e FastAPI para o backend da aplicação [1]."
PRICE = Price(1.0, 2.0, "https://example.test/p", "2026-10-06")
EXTRAS = {"mode_requested": "answer", "mode_used": "context", "routing": None, "grounding": None, "attempts": []}


def _entry(id, tier, provider="ollama", local=True, price=None):
    return ModelEntry(id, provider, id, tier, None, (), False, price, local, False)


class Stub:
    def __init__(self):
        self.calls, self.kw = [], []

    def __call__(self, entry, avail=None):
        stub = self

        class A:
            def generate(self, prompt, temperature=0.0, max_tokens=800, **kw):
                stub.calls.append(entry.id)
                stub.kw.append(kw)
                return GenerationResult(GOOD, 100, 20, 1.0, entry.provider, entry.id)
        return A()


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    for k in ("MG_PRIVACY_CLASSIFY", "ANAMNESIA_ROUTING", "ANAMNESIA_ANSWER_REQUIRE_JEV_STRICT"):
        monkeypatch.delenv(k, raising=False)
    reg = Registry([_entry("m1", 1), _entry("m2", 2, "anthropic", False, PRICE)], "h")
    avail = {p: {"available": True, "models": []} for p in ("ollama", "anthropic")}
    stub = Stub()
    monkeypatch.setattr(ans, "get_registry", lambda: reg)
    monkeypatch.setattr(ans, "get_availability", lambda: avail)
    monkeypatch.setattr(ans, "make_adapter", stub)
    monkeypatch.setattr(ans, "_ollama_name", lambda e, a: e.model)
    monkeypatch.setattr(ans, "get_policy", lambda: preset("economic", enabled=True))
    store = SavedContextStore(tmp_path / "saved_context", rate_per_min=100000)
    import app.memory_store.store as st_mod
    monkeypatch.setattr(st_mod, "get_store", lambda: store)
    return types.SimpleNamespace(stub=stub, store=store)


def _cand(src, snippet="Escolhemos Python e FastAPI para o backend da aplicação.", score=1.0, meta=None):
    return Candidate(candidate_id=src, source_file=src, section="S", snippet=snippet, score=score,
                     origin="baseline", meta=meta or {})


def _result(cands, query="stack backend FastAPI"):
    return types.SimpleNamespace(query=query, candidates=cands, run_id="r1",
                                 metrics={"context_tokens": 50, "pipeline": "baseline"})


def _saved(store, *a, **kw):
    n = store.save(*a, **kw)
    nid = getattr(n, "id", n)
    return nid, store._path_for(nid).name


# -- (c) privacidade ligada ao fluxo real ---------------------------------------------------------
def test_public_vault_candidate_is_not_private(rig):
    assert ans.privacy_signals(_result([_cand("notas/a.md")])) == []


def test_private_visibility_note_marks_private(rig):
    _, f = _saved(rig.store, "Segredo", "conteudo qualquer", scope="project", scope_id="p", project="p",
                  visibility="private", owner="hermes")
    assert "note_visibility_private" in ans.privacy_signals(_result([_cand(f"saved_context/{f}")]))


def test_private_tag_note_marks_private(rig):
    _, f = _saved(rig.store, "Saude", "consulta amanha", tags=["privado"])
    assert "note_tag_private" in ans.privacy_signals(_result([_cand(f"saved_context/{f}")]))


def test_unreadable_saved_note_fails_closed(rig):
    assert ans.privacy_signals(_result([_cand("saved_context/x-0123456789.md")])) == ["note_unreadable"]


def test_text_rules_detect_cpf(rig):
    sig = ans.privacy_signals(_result([_cand("a.md", snippet="CPF 529.982.247-25 do cliente")]))
    assert "text_private_rules" in sig


def test_classifier_off_still_honours_tags(rig, monkeypatch):
    monkeypatch.setenv("MG_PRIVACY_CLASSIFY", "off")
    assert ans.privacy_signals(_result([_cand("a.md", snippet="CPF 529.982.247-25")])) == []
    assert ans.privacy_signals(_result([_cand("a.md", meta={"tags": ["PII"]})])) == ["candidate_tag_private"]


def test_laya_mode_uses_must_stay_local(rig, monkeypatch):
    monkeypatch.setenv("MG_PRIVACY_CLASSIFY", "laya")
    from app.services import laya_decider as ld
    monkeypatch.setattr(ld, "must_stay_local", lambda text, backend=None: True)
    assert "text_must_stay_local" in ans.privacy_signals(_result([_cand("a.md")]))


def test_classifier_exception_fails_closed(rig, monkeypatch):
    monkeypatch.setenv("MG_PRIVACY_CLASSIFY", "laya")
    from app.services import laya_decider as ld

    def boom(text, backend=None):
        raise RuntimeError("x")
    monkeypatch.setattr(ld, "must_stay_local", boom)
    assert ans.privacy_signals(_result([_cand("a.md")])) == ["privacy_classifier_error"]


def test_answer_private_stays_local_and_passes_flag(rig):
    r = _result([_cand("a.md", snippet="Escolhemos Python e FastAPI. CPF 529.982.247-25 do cliente.")])
    out = ans._answer(None, r, "medium", "memory", dict(EXTRAS))
    assert out["privacy"]["private"] is True
    assert rig.stub.calls and set(rig.stub.calls) <= {"m1"}      # nunca o provider hospedado
    assert all(k == {"private": True} for k in rig.stub.kw)


def test_answer_public_does_not_pass_private_kw(rig):
    out = ans._answer(None, _result([_cand("a.md")]), "medium", "memory", dict(EXTRAS))
    assert "privacy" not in out
    assert rig.stub.calls and all(k == {} for k in rig.stub.kw)


def test_metered_adapter_forwards_kwargs():
    from app.routing.spend import MeteredAdapter
    seen = {}

    class Inner:
        def generate(self, prompt, temperature=0.0, max_tokens=800, private=False):
            seen["private"] = private
            return GenerationResult("ok", 1, 1, 1.0, "ollama", "m")
    MeteredAdapter(Inner(), _entry("m1", 1), None).generate("p", private=True)   # local: sem RunSpend
    assert seen == {"private": True}


# -- (d) Colibri: key por ambiente por padrao -------------------------------------------------------
def test_colibri_default_key_via_env():
    from app.services.local_ai.colibri import ColibriRuntime
    assert ColibriRuntime(port=11500)._key_via == "env"
    assert ColibriRuntime(port=11500, key_via="bogus")._key_via == "env"
    assert ColibriRuntime(port=11500, key_via="arg")._key_via == "arg"


# -- (e) aviso JEV em loopback ----------------------------------------------------------------------
def test_jev_warning_suppressed_for_loopback_base_url(monkeypatch):
    from app.api import routes
    fn = next(getattr(routes, n) for n in dir(routes) if n.endswith("warnings") and callable(getattr(routes, n)))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:11500/v1")
    assert not [x for x in fn(None) if x["component"] == "jev"]
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai")
    assert [x for x in fn(None) if x["code"] == "api_key_missing"]


def test_local_first_jev_loopback_is_local_not_network():
    from app.services.local_first import assess
    g = assess({"TYPESAFE_BASE_URL": "http://localhost:11500/v1"}, which=lambda n: None)
    assert g["capabilities"]["jev_judge"]["where"] == "local"
    g2 = assess({"TYPESAFE_API_KEY": "k", "TYPESAFE_BASE_URL": "http://127.0.0.1:1/v1"}, which=lambda n: None)
    assert g2["capabilities"]["jev_judge"]["where"] == "local" and g2["level"] >= 3
    g3 = assess({"TYPESAFE_API_KEY": "k"}, which=lambda n: None)
    assert g3["capabilities"]["jev_judge"]["where"] == "network" and g3["level"] == 2


# -- (f) rank v2 + uso ------------------------------------------------------------------------------
def test_rank_default_is_v1(monkeypatch):
    monkeypatch.delenv("MG_MEMORY_RANK", raising=False)
    assert model.rank_mode() == "v1"


def test_rerank_v2_drops_hard_excluded_and_keeps_vault(tmp_path):
    st = SavedContextStore(tmp_path / "saved_context", rate_per_min=100000)
    _, fa = _saved(st, "A", "alfa conteudo")
    _, fc = _saved(st, "C", "gama conteudo", initial_status="candidate")
    cands = [_cand(f"saved_context/{fa}", score=1.0), _cand(f"saved_context/{fc}", score=0.8),
             _cand("vault/x.md", score=0.7)]
    out, m = model.rerank_candidates(st, cands)
    srcs = [x.source_file for x in out]
    assert f"saved_context/{fc}" not in srcs and "vault/x.md" in srcs and len(srcs) == 2
    assert m == {"memory_rank": "v2", "memory_rank_excluded": 1}
    assert "rank_v2" in next(x for x in out if x.source_file.startswith("saved_context/")).meta


def test_rerank_empty_is_noop(tmp_path):
    st = SavedContextStore(tmp_path / "saved_context", rate_per_min=100000)
    assert model.rerank_candidates(st, []) == ([], {})


def test_record_delivered_usage_counts_only_saved_notes(tmp_path):
    st = SavedContextStore(tmp_path / "saved_context", rate_per_min=100000)
    nid, f = _saved(st, "A", "alfa conteudo")
    srcs = [types.SimpleNamespace(file=f"saved_context/{f}"), types.SimpleNamespace(file="vault/x.md")]
    assert model.record_delivered_usage(st, srcs, run_id="r") == 1
    assert model.usage_map(st)[nid]["usage_count"] == 1
    assert model.record_delivered_usage(object(), srcs) == 0      # nunca levanta


# -- (b) ciclo local_ai -----------------------------------------------------------------------------
def test_local_ai_has_no_import_cycle():
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    try:
        import check_import_cycles as cyc
    finally:
        sys.path.pop(0)
    bad = [c for c in cyc.tarjan_sccs(cyc.build_graph(root, "app"))
           if any(m.startswith("app.services.local_ai") for m in c)]
    assert bad == []
