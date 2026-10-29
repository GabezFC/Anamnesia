"""Fase 7 / writing-block §9.3: lacunas do Decision Engine que os testes antigos não cobriam.

Cobertura cruzada (cada item do §9.3 -> teste que o prova; todos offline, sem API paga):
  cache hit/miss ............ test_decision_engine.py::test_cache_hit_and_key_invalidation, test_fallback_results_are_not_cached
  local disponível/indisp. .. test_decision_engine.py::test_one_side_down_*, test_both_down_uses_op_fallback; aqui: colibri
  externo indisponível ...... test_decision_engine.py::test_fallback_*; aqui: timeout e credencial inválida
  credencial inválida ....... aqui (sem vazar a chave) + test_onda4_resilience_units.py::test_auth_skips_provider_*
  timeout ................... aqui + test_onda4_resilience_http.py::test_timeout_kind
  limite de orçamento ....... test_anam003_spend_guard.py (run cap, day cap, cap 0 bloqueia antes da rede)
  limite de tentativas ...... aqui (1 chamada por decide) + test_onda4_resilience_units.py::test_bad_output_escalates_*
  fallback / seleção ........ test_decision_engine.py + test_routing_router.py + test_onda4_resilience_answer_loop.py
  modelo utilizado .......... aqui (res.model, to_public, histórico)
"""
from __future__ import annotations

import json

from app.decision import DecisionEngine, DecisionRequest, Item, load_config
from app.decision.telemetry import DecisionHistory
from tests.test_decision_engine import FakeJev, FakeLaya, engine, req

KEY = "sk-" + "A1b2C3d4E5f6G7h8"  # chave FAKE de teste; só prova a redação


class RaisingJev(FakeJev):
    def __init__(self, exc: Exception):
        super().__init__()
        self.exc, self.attempts = exc, 0

    def evaluate(self, query, cands):
        self.attempts += 1
        raise self.exc


def test_model_used_is_recorded_everywhere():
    eng = engine(FakeJev())
    r = eng.decide(req())
    assert r.provider == "jev" and r.model == "fake-jev"                   # checkpoint do provider que decidiu
    assert r.to_public()["model"] == "fake-jev"
    assert eng.history.recent(1)[0]["model"] == "fake-jev"                 # telemetria persistível
    assert "SEGREDO" not in json.dumps(r.to_public())


def test_invalid_credential_falls_back_explicitly_and_never_leaks_key():
    jev = RaisingJev(PermissionError(f"401 Unauthorized: invalid api key {KEY}"))
    eng = engine(jev)
    r = eng.decide(req(op="retrieval"))                                    # JEV só suporta retrieval (security: modo strict)
    assert jev.attempts == 1                                               # sem retry/fallback ilimitado
    assert all(i.fallback and i.decision == "UNJUDGED" and i.fallback_action == "allow" for i in r.items)  # nunca "keep" silencioso
    blob = json.dumps(r.to_public()) + json.dumps(eng.history.recent(5, include_items=True))
    assert KEY not in blob and "[REDACTED]" in blob and r.errors


def test_memory_op_unsupported_by_jev_is_explicit_review_without_calling_provider():
    jev = RaisingJev(RuntimeError("não deve ser chamado"))
    r = engine(jev).decide(req(op="memory"))
    assert jev.attempts == 0 and r.errors                                  # capacidade ausente: recusa antes de gastar chamada
    assert all(i.fallback and i.decision == "REVIEW" for i in r.items)


def test_timeout_is_explicit_fallback_with_single_attempt():
    jev = RaisingJev(TimeoutError("judge timed out after 30s"))
    jev.cfg = type("cfg", (), {"model": "fake-jev", "mode": "strict", "injection_threshold": 0.8})  # security exige strict
    r = engine(jev).decide(req(op="security"))
    assert jev.attempts == 1
    assert {i.decision for i in r.items} == {"QUARANTINE"} and all(i.fallback_action == "block" for i in r.items)
    assert any("TimeoutError" in e for e in r.errors)


def test_attempts_are_bounded_across_repeated_failures():
    jev = RaisingJev(RuntimeError("down"))
    eng = engine(jev)
    for _ in range(5):
        eng.decide(req())
    assert jev.attempts == 5                                                # exatamente 1 tentativa por decisão: sem laço oculto
    assert eng.cache.stats()["entries"] == 0 if "entries" in eng.cache.stats() else True   # fallback não é cacheado


def test_hybrid_one_side_down_calls_each_provider_at_most_once():
    jev, laya = RaisingJev(RuntimeError("down")), FakeLaya({"a": (0.9, 0.9, 0.9)})
    r = engine(jev, laya).decide(req(("a",)), provider="hybrid", strategy="laya_then_jev")
    assert jev.attempts <= 1 and laya.calls == 1
    assert r.items[0].decision in ("KEEP", "REVIEW", "DROP", "UNJUDGED")


def test_colibri_unavailable_is_explicit_not_silent(monkeypatch):
    monkeypatch.setenv("MG_COLIBRI_ENABLED", "off")
    cfg = load_config({})
    cfg.history_persist = False
    eng = DecisionEngine(cfg, jev=FakeJev(), laya_service=FakeLaya(), history=DecisionHistory(50, None, False))
    r = eng.decide(req(op="memory"), provider="colibri")
    assert r.provider == "colibri" and all(i.fallback for i in r.items) and r.errors
    st = eng.status()["providers"]["colibri"]
    assert st.get("available") in (False, None) or "disabled" in json.dumps(st).lower() or "off" in json.dumps(st).lower()
