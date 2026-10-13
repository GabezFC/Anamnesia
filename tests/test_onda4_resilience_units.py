"""Onda 4 / ANA-177, 178, 180, 187, 190: pure units (decision table, retry, breaker, health, budget warn)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.adapters.models.errors import ERROR_KINDS
from app.adapters.models.providers import GenerationResult
from app.routing import circuit_breaker as cb
from app.routing import health as hl
from app.routing import resilience as rs
from app.routing import retry as rt
from app.routing.registry import ModelEntry


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in ("ANAMNESIA_RETRY", "ANAMNESIA_CIRCUIT_BREAKER", "ANAMNESIA_FALLBACK_BY_CAUSE", "ANAMNESIA_HEALTH",
              "ANAMNESIA_HEALTH_PROBE", "ANAMNESIA_ALLOW_NETWORK_TEST", "ANAMNESIA_RETRY_MAX"):
        monkeypatch.delenv(k, raising=False)
    cb.reset_breaker()
    hl.reset_tracker()


class Clock:
    def __init__(self):
        self.t, self.sleeps = 100.0, []

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def now(self):
        return self.t


def R(kind=None, status=None, ra=None, answer="x"):
    return GenerationResult(None if kind else answer, 1, 1, 5.0, "p", "m", f"err {kind}" if kind else None,
                            error_kind=kind, status_code=status, retry_after=ra)


# ----------------------------------------------------------------------------------- ANA-177
def test_decide_table_covers_every_kind():
    for k in ERROR_KINDS:
        assert isinstance(rs.decide(k, 5), rs.Action)
    assert rs.decide("rate_limit", 0, 7.0, max_retries=2) == rs.Action(rs.RETRY, 7.0, "rate_limit: backoff/Retry-After")
    assert rs.decide("rate_limit", 2, 7.0, max_retries=2).name == rs.SWITCH_PROVIDER
    assert rs.decide("timeout", 0).name == rs.RETRY and rs.decide("timeout", 1).name == rs.SWITCH_PROVIDER
    assert rs.decide("provider_down", 1).name == rs.SWITCH_PROVIDER
    assert rs.decide("auth").name == rs.SKIP_PROVIDER and rs.decide("model_not_found").name == rs.SKIP_PROVIDER
    assert rs.decide("context_overflow", has_larger_window=True).name == rs.ESCALATE_LARGER_WINDOW
    assert rs.decide("context_overflow").name == rs.ABORT
    assert rs.decide("bad_output").name == rs.ESCALATE_TIER and rs.decide("other").name == rs.ESCALATE_TIER


def E(i, prov, tier, win=None):
    return ModelEntry(i, prov, i, tier, win, (), False, None, prov == "ollama", False)


class Reg:
    def __init__(self, *m):
        self.models = list(m)

    def get(self, i):
        return next(m for m in self.models if m.id == i)


DEC = SimpleNamespace(model_id="a1", fallback_chain=["a1", "b1", "c2"], max_escalations=2)
REG = Reg(E("a1", "ollama", 1, 4000), E("b1", "openai", 1, 4000), E("c2", "anthropic", 2, 200000))


def att(model, kind, ra=None):
    return {"model_id": model, "error_kind": kind, "retry_after": ra}


def test_switch_provider_stays_in_same_tier(monkeypatch):
    monkeypatch.setenv(rs.FALLBACK_FLAG, "1")
    a = [att("a1", "rate_limit", 1.0)]
    assert rs.next_after_failure(DEC, REG, REG.get("a1"), a, {"retries": 0}, 1) == "b1"
    assert a[0]["fallback_action"] == rs.SWITCH_PROVIDER


def test_auth_skips_provider_and_does_not_escalate_same_provider(monkeypatch):
    monkeypatch.setenv(rs.FALLBACK_FLAG, "1")
    reg = Reg(E("a1", "openai", 1), E("a2", "openai", 2), E("c3", "anthropic", 3))
    dec = SimpleNamespace(fallback_chain=["a1", "a2", "c3"], max_escalations=2)
    a = [att("a1", "auth")]
    assert rs.next_after_failure(dec, reg, reg.get("a1"), a, {}, 1) == "c3"   # skips a2 (same bad provider)


def test_context_overflow_larger_window_or_abort(monkeypatch):
    monkeypatch.setenv(rs.FALLBACK_FLAG, "1")
    a = [att("a1", "context_overflow")]
    assert rs.next_after_failure(DEC, REG, REG.get("a1"), a, {}, 1) == "c2"      # 200k > 4k (b1 has same window)
    reg = Reg(E("a1", "ollama", 1, 4000), E("b1", "openai", 1, 4000))
    dec = SimpleNamespace(fallback_chain=["a1", "b1"], max_escalations=2)
    a = [att("a1", "context_overflow")]
    assert rs.next_after_failure(dec, reg, reg.get("a1"), a, {}, 1) is None
    assert a[0]["fallback_action"] == rs.ABORT


def test_bad_output_escalates_tier_and_respects_max_escalations(monkeypatch):
    monkeypatch.setenv(rs.FALLBACK_FLAG, "1")
    a = [att("a1", "bad_output")]
    assert rs.next_after_failure(DEC, REG, REG.get("a1"), a, {}, 1) == "b1"
    assert rs.next_after_failure(DEC, REG, REG.get("a1"), a, {}, 3) is None


def test_flag_off_or_no_kind_uses_legacy_next_model():
    a = [att("a1", "auth")]
    dec = SimpleNamespace(model_id="a1", fallback_chain=["b1", "c2"], max_escalations=2)   # real chains exclude the primary
    assert rs.next_after_failure(dec, REG, REG.get("a1"), a, {}, 1) == "b1"     # legacy: chain[failed-1]
    assert "fallback_action" not in a[0]


def test_open_circuit_is_skipped_when_choosing(monkeypatch):
    monkeypatch.setenv(rs.FALLBACK_FLAG, "1")
    monkeypatch.setenv("ANAMNESIA_CIRCUIT_BREAKER", "1")
    b = cb.get_breaker()
    for _ in range(3):
        b.record_failure(cb.key_for("openai", "b1"), "provider_down")
    a = [att("a1", "timeout")]
    assert rs.next_after_failure(DEC, REG, REG.get("a1"), a, {"retries": 1}, 1) == "c2"


# ----------------------------------------------------------------------------------- ANA-178
def test_backoff_is_exponential_capped_and_deterministic():
    p = rt.RetryPolicy(jitter=0.0, base_delay_s=1, max_delay_s=5)
    assert [rt.backoff_delay(i, p) for i in range(4)] == [1, 2, 4, 5]
    pj = rt.RetryPolicy(jitter=0.25)
    assert rt.backoff_delay(0, pj) == rt.backoff_delay(0, pj)
    assert 0.375 <= rt.backoff_delay(0, pj) <= 0.625
    assert rt.backoff_delay(0, pj, jitter_fn=lambda a: 1.0) == pytest.approx(0.625)
    assert rt.backoff_delay(0, pj, retry_after=9) == 9


def test_retry_sequences_with_fake_time():
    c, seq = Clock(), [R("provider_down", 500), R("timeout"), R()]
    out = rt.call_with_retry(lambda: seq.pop(0), rt.RetryPolicy(jitter=0.0), sleep=c.sleep, clock=c.now)
    assert out.result.answer == "x" and out.retries == 2 and c.sleeps == [0.5, 1.0]
    assert [s["kind"] for s in out.log] == ["provider_down", "timeout"]


def test_retry_exception_path_and_non_retryable():
    import httpx
    c, calls = Clock(), []

    def boom():
        calls.append(1)
        raise httpx.ReadTimeout("t")
    out = rt.call_with_retry(boom, rt.RetryPolicy(max_retries=1), sleep=c.sleep, clock=c.now)
    assert len(calls) == 2 and isinstance(out.exc, httpx.ReadTimeout) and out.gave_up == "max_retries"
    for kind in ("auth", "model_not_found", "context_overflow", "bad_output", "other"):
        c, n = Clock(), []
        out = rt.call_with_retry(lambda: (n.append(1), R(kind))[1], sleep=c.sleep, clock=c.now)
        assert len(n) == 1 and c.sleeps == [] and out.gave_up == "not_retryable"


def test_total_time_budget_stops_retries():
    c = Clock()
    out = rt.call_with_retry(lambda: R("rate_limit", 429, 30.0), rt.RetryPolicy(total_budget_s=20), sleep=c.sleep,
                             clock=c.now)
    assert out.gave_up == "time_budget" and c.sleeps == [] and out.retries == 0


def test_retry_flag_default_off(monkeypatch):
    assert rt.retry_enabled() is False
    monkeypatch.setenv("ANAMNESIA_RETRY", "1")
    assert rt.retry_enabled() is True
    monkeypatch.setenv("ANAMNESIA_RETRY_MAX", "9")
    assert rt.RetryPolicy.from_env().max_retries == 2          # hard cap = 2


# ----------------------------------------------------------------------------------- ANA-187
def test_breaker_opens_half_opens_and_closes():
    c = Clock()
    b = cb.CircuitBreaker(3, 60, 30, clock=c.now)
    k = "p/m"
    for _ in range(2):
        b.record_failure(k, "timeout")
    assert b.state(k) == cb.CLOSED and b.allow(k)
    b.record_failure(k, "timeout")
    assert b.state(k) == cb.OPEN and not b.allow(k)
    c.t += 29
    assert not b.allow(k)
    c.t += 2
    assert b.state(k) == cb.HALF_OPEN
    assert b.allow(k) and not b.allow(k)             # exactly one probe
    b.record_failure(k, "provider_down")             # probe fails -> re-open
    assert b.state(k) == cb.OPEN
    c.t += 31
    assert b.allow(k)
    b.record_success(k)
    assert b.state(k) == cb.CLOSED and b.allow(k)


def test_breaker_window_expiry_and_non_tripping_kinds():
    c = Clock()
    b = cb.CircuitBreaker(3, 60, 30, clock=c.now)
    b.record_failure("k", "timeout")
    b.record_failure("k", "timeout")
    c.t += 61
    b.record_failure("k", "timeout")
    assert b.state("k") == cb.CLOSED                  # first two aged out of the window
    for kind in ("bad_output", "context_overflow", "other", None):
        for _ in range(5):
            b.record_failure("z", kind)
    assert b.state("z") == cb.CLOSED


def test_breaker_state_is_serialisable_and_restorable():
    c = Clock()
    b = cb.CircuitBreaker(2, 60, 30, clock=c.now)
    b.record_failure("a/b", "rate_limit")
    b.record_failure("a/b", "rate_limit")
    snap = b.snapshot()
    json.dumps(snap)
    assert snap["a/b"]["state"] == "open" and snap["a/b"]["retry_in_s"] == 30.0 and snap["a/b"]["opens"] == 1
    c2 = Clock()
    b2 = cb.CircuitBreaker(2, 60, 30, clock=c2.now)
    b2.restore(snap)
    assert b2.state("a/b") == cb.OPEN
    c2.t += 31
    assert b2.state("a/b") == cb.HALF_OPEN


def test_guarded_generate_flags_off_is_plain_call_and_exceptions_propagate():
    calls = []

    def mk(entry, avail):
        class A:
            def generate(self, prompt, **kw):
                calls.append(prompt)
                raise RuntimeError("raw")
        return A()
    with pytest.raises(RuntimeError):
        rs.guarded_generate(E("a1", "ollama", 1), mk, {}, "p", {})
    assert calls == ["p"] and cb.get_breaker().snapshot() == {}         # nothing recorded


def test_guarded_generate_breaker_blocks_after_failures(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_CIRCUIT_BREAKER", "1")
    calls = []

    def mk(entry, avail):
        class A:
            def generate(self, prompt, **kw):
                calls.append(1)
                return R("provider_down", 500)
        return A()
    e = E("a1", "openai", 1)
    for _ in range(3):
        rs.guarded_generate(e, mk, {}, "p", {})
    info = {}
    r = rs.guarded_generate(e, mk, {}, "p", info)
    assert len(calls) == 3 and info["circuit_open"] and r.error_kind == "provider_down"


def test_guarded_generate_retry_uses_injected_sleep(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_RETRY", "1")
    c = Clock()
    monkeypatch.setattr(rs, "SLEEP", c.sleep)
    monkeypatch.setattr(rs, "CLOCK", c.now)
    seq = [R("rate_limit", 429, 4.0), R()]

    def mk(entry, avail):
        return SimpleNamespace(generate=lambda p, **kw: seq.pop(0))
    info = {}
    r = rs.guarded_generate(E("a1", "openai", 1), mk, {}, "p", info)
    assert r.answer == "x" and c.sleeps == [4.0] and info["retries"] == 1


# ----------------------------------------------------------------------------------- ANA-190
def test_percentiles_and_stats():
    t = hl.HealthTracker()
    for i in range(1, 11):
        t.record("m", True, i * 10)
    t.record("m", False, 5, "timeout")
    s = t.stats("m")
    assert s["n"] == 11 and s["errors"] == 1 and s["error_rate"] == pytest.approx(1 / 11, abs=1e-4)
    assert s["p50_ms"] == 50 and s["p95_ms"] == 100 and s["last_error_kind"] == "timeout"
    assert hl.percentile([], 50) is None


def test_verdicts_unknown_healthy_degraded_unhealthy():
    t = hl.HealthTracker()
    t.record("m", True, 1)
    t.record("m", True, 1)
    assert t.verdict("m") == "unknown"
    t.record("m", True, 1)
    assert t.verdict("m") == "healthy"
    for _ in range(2):
        t.record("m", False, None, "timeout")
    assert t.verdict("m") == "degraded"
    for _ in range(3):
        t.record("m", False, None, "timeout")
    assert t.verdict("m") == "unhealthy"


def test_fault_injection_key_present_is_not_healthy(monkeypatch):
    """A provider whose key is configured but whose calls fail must NOT be reported healthy."""
    monkeypatch.setenv("ANAMNESIA_HEALTH", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-not-real")
    mode = {"fail": True}

    def mk(entry, avail):
        return SimpleNamespace(generate=lambda p, **kw: R("provider_down", 503) if mode["fail"] else R())
    e = E("b1", "openai", 1)
    for _ in range(4):
        rs.guarded_generate(e, mk, {}, "p", {})
    key = cb.key_for("openai", "b1")
    assert hl.get_tracker().verdict(key) == "unhealthy"
    mode["fail"] = False
    for _ in range(8):
        rs.guarded_generate(e, mk, {}, "p", {})
    assert hl.get_tracker().verdict(key) in ("degraded", "healthy")
    assert hl.get_tracker().stats(key)["p50_ms"] is not None
    json.dumps(hl.health_report())


def test_probes_are_opt_in_and_offline_by_default(monkeypatch):
    def no_http(*a, **k):
        raise AssertionError("must not touch the network")
    assert "skipped" in hl.probe_ollama(http_get=no_http)

    class Cloud:
        def list_models(self):
            raise AssertionError("must not be called")
    assert "skipped" in hl.probe_cloud(Cloud())
    monkeypatch.setenv("ANAMNESIA_HEALTH_PROBE", "1")

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}
    r = hl.probe_ollama(http_get=lambda url, timeout: Resp())
    assert r["ok"] is True and r["models"] == 1
    monkeypatch.setenv("ANAMNESIA_ALLOW_NETWORK_TEST", "1")
    assert hl.probe_cloud(SimpleNamespace(list_models=lambda: ["a", "b"]))["models"] == 2

    def bad():
        raise TimeoutError("t")
    assert hl.probe_cloud(SimpleNamespace(list_models=bad))["error_kind"] == "timeout"


def test_connections_api_exposes_state_only_when_flagged(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import connections
    app = FastAPI()
    app.include_router(connections.router)
    tc = TestClient(app, client=("127.0.0.1", 5))
    assert "resilience" not in tc.get("/api/connections").json()
    monkeypatch.setenv("ANAMNESIA_CIRCUIT_BREAKER", "1")
    for _ in range(3):
        cb.get_breaker().record_failure("openai/x", "auth")
    body = tc.get("/api/connections").json()
    assert body["resilience"]["circuits"]["openai/x"]["state"] == "open"
    assert tc.get("/api/connections/resilience/state").json()["circuits"]["openai/x"]["opens"] == 1


# ----------------------------------------------------------------------------------- ANA-180
def test_budget_warn_default_records_but_never_blocks(tmp_path, monkeypatch):
    from app.gateway import budget_guard as bg
    from tests.test_budget_and_measurement import db_with_spend, plan
    monkeypatch.delenv(bg.ENV_FLAG, raising=False)
    monkeypatch.delenv(bg.WARN_FLAG, raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    db = db_with_spend(tmp_path, ceiling_day=0.00001)
    pl = plan("graphify_jev")
    new, extra = bg.BudgetGuard(ttl_s=0).apply(pl, db)
    assert new is pl and extra["budget_status"] == "exceeded" and extra["budget_mode"] == "warn"
    assert "budget_degraded" not in extra and extra["budget_warning"]
    free = plan("baseline")
    assert bg.BudgetGuard(ttl_s=0).apply(free, db) == (free, {})
    monkeypatch.setenv(bg.ENV_FLAG, "1")                        # enforce stays opt-in and still degrades
    new, extra = bg.BudgetGuard(ttl_s=0).apply(pl, db)
    assert new.pipeline == "baseline" and "budget_mode" not in extra
    monkeypatch.setenv(bg.ENV_FLAG, "0")
    monkeypatch.setenv(bg.WARN_FLAG, "0")
    assert bg.BudgetGuard(ttl_s=0).apply(pl, db) == (pl, {})
