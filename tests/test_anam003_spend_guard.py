"""ANAM-003: teto de gasto acumulado por run/dia, consentimento de egress e tabela de precos. Provider fake, sem rede."""
from __future__ import annotations

import pytest

from app.adapters.models.errors import BudgetExceeded, PaidCallsDisabled, ensure_paid_allowed, paid_calls_enabled
from app.adapters.models.providers import GenerationResult
from app.routing import answer as ans
from app.routing import spend as sp
from app.routing.registry import ModelEntry, Price
from config import pricing

# reutiliza o fixture `env` (gateway + registry m1 local, m2 anthropic c/ preco, m3 openai sem preco) e o stub
from test_memory_search_mode import GOOD, BAD, PRICE, Q, env, _entry  # noqa: F401


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (sp.ENFORCE_ENV, sp.RUN_ENV, sp.DAY_ENV, pricing.PRICING_FILE_ENV, "ANAMNESIA_PAID_CALLS"):
        monkeypatch.delenv(k, raising=False)
    sp.DAY.reset()
    yield
    sp.DAY.reset()


class FakeAdapter:
    """Provider fake: devolve texto com uso fixo; conta chamadas."""

    def __init__(self, tin=1000, tout=300, text="x"):
        self.tin, self.tout, self.text, self.calls = tin, tout, text, 0

    def generate(self, prompt, temperature=0.0, max_tokens=800):
        self.calls += 1
        return GenerationResult(self.text, self.tin, self.tout, 1.0, "anthropic", "m")


def paid_entry(price=Price(10.0, 50.0, "u", "2026-10-06"), id="p"):
    return ModelEntry(id, "anthropic", "claude-x", 2, None, (), False, price, False, False)


# ------------------------------------------------------------------ consentimento
@pytest.mark.parametrize("val", [None, "", "0", "maybe"])
def test_consent_never_implicit(monkeypatch, val):
    if val is not None:
        monkeypatch.setenv("ANAMNESIA_PAID_CALLS", val)
    assert paid_calls_enabled() is False
    with pytest.raises(PaidCallsDisabled):
        ensure_paid_allowed("anthropic")
    ensure_paid_allowed("ollama")          # local nunca exige consentimento


def test_consent_explicit_allows(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    ensure_paid_allowed("anthropic")


def test_adapter_without_consent_does_not_touch_network(monkeypatch):
    import httpx
    from app.adapters.models.providers import OpenAICompatibleAdapter
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rede!")))
    r = OpenAICompatibleAdapter("https://api.openai.com/v1", "m", "k", "openai").generate("x")
    assert r.answer is None and "ANAMNESIA_PAID_CALLS" in r.error


# ------------------------------------------------------------------ tabela de precos
def test_estimate_cost_components():
    p = {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75}
    usd, basis = pricing.estimate_cost("m", "anthropic", tokens_in=1_000_000, tokens_out=1_000_000,
                                       cache_read=1_000_000, cache_write=1_000_000, thinking=1_000_000,
                                       embedding=1_000_000, price=p)
    # thinking -> preco de output; embedding -> preco de input
    assert basis == "verified" and usd == pytest.approx(3 + 15 + 0.3 + 3.75 + 15 + 3)


def test_estimate_cost_local_zero_and_unknown_pessimistic():
    assert pricing.estimate_cost("qwen", "ollama", tokens_in=10**9, tokens_out=10**9) == (0.0, "local_zero")
    usd, basis = pricing.estimate_cost("modelo-sem-preco", "openai", tokens_in=1_000_000, tokens_out=0)
    assert basis == "unknown_price_upper_bound" and usd == pytest.approx(pricing.DEFAULT_UNKNOWN_PRICE["input"])


def test_pricing_file_override_and_bad_file(monkeypatch, tmp_path):
    f = tmp_path / "p.json"
    f.write_text('{"modelo-x": {"input": 1.0, "output": 2.0, "cache_read": 0.1}}', encoding="utf-8")
    monkeypatch.setenv(pricing.PRICING_FILE_ENV, str(f))
    assert pricing.estimate_cost("modelo-x", "openai", tokens_in=1_000_000, cache_read=1_000_000)[0] == pytest.approx(1.1)
    f.write_text("{nao eh json", encoding="utf-8")
    assert pricing.estimate_cost("modelo-x", "openai", tokens_in=1_000_000)[1] == "unknown_price_upper_bound"


# ------------------------------------------------------------------ teto por run / dia
def test_enforce_default_on_and_caps(monkeypatch):
    assert sp.enforce_enabled() is True and sp.run_cap() == sp.DEFAULT_RUN_USD and sp.day_cap() == sp.DEFAULT_DAY_USD
    monkeypatch.setenv(sp.RUN_ENV, "lixo")
    assert sp.run_cap() == sp.DEFAULT_RUN_USD
    monkeypatch.setenv(sp.ENFORCE_ENV, "0")
    assert sp.enforce_enabled() is False


def test_run_cap_never_exceeded_over_many_attempts(monkeypatch):
    monkeypatch.setenv(sp.RUN_ENV, "0.02")
    run, inner = sp.RunSpend(), FakeAdapter()
    ad = sp.MeteredAdapter(inner, paid_entry(), run)
    blocked = 0
    for _ in range(50):                      # retry/escalation sem fim
        try:
            ad.generate("p" * 300, max_tokens=300)
        except BudgetExceeded:
            blocked += 1
    assert blocked > 0 and inner.calls < 50
    assert run.spent <= 0.02 + 1e-9          # NUNCA excede o teto
    assert sp.DAY.spent() == pytest.approx(run.spent)


def test_day_cap_shared_across_runs(monkeypatch):
    monkeypatch.setenv(sp.RUN_ENV, "10")
    monkeypatch.setenv(sp.DAY_ENV, "0.02")
    total = 0.0
    for _ in range(20):
        run = sp.RunSpend()
        try:
            sp.MeteredAdapter(FakeAdapter(), paid_entry(), run).generate("p" * 300, max_tokens=300)
        except BudgetExceeded:
            pass
        total += run.spent
    assert sp.DAY.spent() <= 0.02 + 1e-9 and total == pytest.approx(sp.DAY.spent())


def test_zero_cap_blocks_every_paid_call_before_network(monkeypatch):
    monkeypatch.setenv(sp.RUN_ENV, "0")
    inner = FakeAdapter()
    with pytest.raises(BudgetExceeded):
        sp.MeteredAdapter(inner, paid_entry(), sp.RunSpend()).generate("oi", max_tokens=10)
    assert inner.calls == 0


def test_unpriced_paid_model_is_bounded_not_free(monkeypatch):
    monkeypatch.setenv(sp.RUN_ENV, "0.001")
    inner = FakeAdapter()
    with pytest.raises(BudgetExceeded):
        sp.MeteredAdapter(inner, paid_entry(price=None), sp.RunSpend()).generate("oi", max_tokens=300)
    assert inner.calls == 0


def test_exception_keeps_reservation(monkeypatch):
    class Boom:
        def generate(self, *a, **k):
            raise TimeoutError("x")
    run = sp.RunSpend()
    with pytest.raises(TimeoutError):
        sp.MeteredAdapter(Boom(), paid_entry(), run).generate("oi", max_tokens=100)
    assert run.spent > 0


def test_enforce_off_is_explicit_opt_out(monkeypatch):
    monkeypatch.setenv(sp.ENFORCE_ENV, "0")
    monkeypatch.setenv(sp.RUN_ENV, "0")
    inner = FakeAdapter()
    sp.MeteredAdapter(inner, paid_entry(), sp.RunSpend()).generate("oi", max_tokens=10)
    assert inner.calls == 1


def test_local_cost_zero_unchanged(monkeypatch):
    """Benchmark/local com custo 0: nunca bloqueado, nunca contabilizado."""
    monkeypatch.setenv(sp.RUN_ENV, "0")
    monkeypatch.setenv(sp.DAY_ENV, "0")
    run, inner = sp.RunSpend(), FakeAdapter(tin=10**6, tout=10**6)
    ad = sp.MeteredAdapter(inner, _entry("m1", 1), run)
    for _ in range(5):
        assert ad.generate("x" * 10_000, max_tokens=4000).answer == "x"
    assert inner.calls == 5 and run.spent == 0.0 and sp.DAY.spent() == 0.0


# ------------------------------------------------------------------ loop de resposta (escalation)
def test_answer_loop_stops_escalating_when_cap_hit(env, monkeypatch):
    monkeypatch.setenv(sp.RUN_ENV, "0.0005")          # m2 (preco conhecido) cabe; m3 (sem preco) nao
    env.stub.replies.update(m1=BAD, m2=BAD, m3=GOOD)
    b = env.client.post("/memory/search", json={**Q, "mode": "answer"}).json()
    assert "m3" not in env.stub.calls                 # o 3o modelo nunca foi chamado (nem na rede)
    assert b["mode_used"] == "context" and b["fallback_reason"] in ("grounding_failed", "generation_failed")
    blocked = [a for a in b["attempts"] if a["model_id"] == "m3"]
    assert blocked and "BudgetExceeded" in blocked[0]["error"]


def test_answer_loop_unchanged_with_default_caps(env):
    env.stub.replies.update(m1=BAD, m2=GOOD)
    b = env.client.post("/memory/search", json={**Q, "mode": "answer"}).json()
    assert b["mode_used"] == "answer" and env.stub.calls == ["m1", "m2"]
