"""Onda 4 / ANA-177/178/187: the real `_answer` loop with scripted adapters and flags on/off. Offline, fake time."""
from __future__ import annotations

import pytest

from app.adapters.models.providers import GenerationResult
from app.routing import answer as ans
from app.routing import circuit_breaker as cb
from app.routing import health as hl
from app.routing import resilience as rs
from tests.test_memory_search_mode import BAD, GOOD, Q, env  # noqa: F401  (fixture reuse)

FLAGS = ("ANAMNESIA_RETRY", "ANAMNESIA_CIRCUIT_BREAKER", "ANAMNESIA_FALLBACK_BY_CAUSE", "ANAMNESIA_HEALTH")


class Script:
    """replies[model_id] = list of outcomes consumed in order: str answer | (kind, status, retry_after) | Exception."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, entry, avail=None):
        s = self

        class A:
            def generate(self, prompt, temperature=0.0, max_tokens=800):
                s.calls.append(entry.id)
                q = s.replies[entry.id]
                r = q.pop(0) if len(q) > 1 else q[0]
                if isinstance(r, Exception):
                    raise r
                if isinstance(r, tuple):
                    return GenerationResult(None, None, None, 1.0, entry.provider, entry.id, f"err {r[0]}",
                                            error_kind=r[0], status_code=r[1], retry_after=r[2])
                return GenerationResult(r, 100, 20, 1.0, entry.provider, entry.id)
        return A()


@pytest.fixture
def lab(env, monkeypatch):  # noqa: F811
    for k in FLAGS:
        monkeypatch.delenv(k, raising=False)
    cb.reset_breaker()
    hl.reset_tracker()
    sleeps = []
    monkeypatch.setattr(rs, "SLEEP", sleeps.append)
    env.sleeps = sleeps

    def script(replies):
        s = Script(replies)
        monkeypatch.setattr(ans, "make_adapter", s)
        env.s = s
        return s
    env.script = script
    env.flag = monkeypatch.setenv
    return env


def ask(lab):
    return lab.client.post("/memory/search", json={**Q, "mode": "answer"}).json()


def test_flags_off_is_legacy_one_call_then_next_tier(lab):
    lab.script({"m1": [("rate_limit", 429, 2.0)], "m2": [GOOD], "m3": [GOOD]})
    b = ask(lab)
    assert lab.s.calls == ["m1", "m2"] and lab.sleeps == [] and b["mode_used"] == "answer"
    a = b["attempts"][0]
    assert a["error_kind"] == "rate_limit" and "retries" not in a and "fallback_action" not in a


def test_retry_flag_retries_same_model_with_retry_after(lab):
    lab.flag("ANAMNESIA_RETRY", "1")
    lab.script({"m1": [("rate_limit", 429, 2.0), GOOD], "m2": [GOOD], "m3": [GOOD]})
    b = ask(lab)
    assert lab.s.calls == ["m1", "m1"] and lab.sleeps == [2.0]
    assert b["mode_used"] == "answer" and b["routing"]["model_id"] == "m1"


def test_retry_flag_does_not_retry_auth(lab):
    lab.flag("ANAMNESIA_RETRY", "1")
    lab.script({"m1": [("auth", 401, None)], "m2": [GOOD], "m3": [GOOD]})
    ask(lab)
    assert lab.s.calls == ["m1", "m2"] and lab.sleeps == []


def test_fallback_by_cause_rate_limit_retries_then_escalates(lab):
    lab.flag("ANAMNESIA_RETRY", "1")
    lab.flag("ANAMNESIA_FALLBACK_BY_CAUSE", "1")
    lab.script({"m1": [("rate_limit", 429, 1.0)], "m2": [GOOD], "m3": [GOOD]})
    b = ask(lab)
    assert lab.s.calls == ["m1", "m1", "m1", "m2"] and lab.sleeps == [1.0, 1.0]
    a = b["attempts"][0]
    assert a["retries"] == 2 and a["fallback_action"] == rs.SWITCH_PROVIDER


def test_fallback_by_cause_auth_bans_provider(lab):
    lab.flag("ANAMNESIA_FALLBACK_BY_CAUSE", "1")
    lab.script({"m1": [("auth", 401, None)], "m2": [GOOD], "m3": [GOOD]})
    b = ask(lab)
    assert b["attempts"][0]["fallback_action"] == rs.SKIP_PROVIDER and lab.s.calls == ["m1", "m2"]


def test_fallback_by_cause_overflow_aborts_without_larger_window(lab):
    lab.flag("ANAMNESIA_FALLBACK_BY_CAUSE", "1")
    lab.script({"m1": [("context_overflow", 400, None)], "m2": [GOOD], "m3": [GOOD]})
    b = ask(lab)       # registry in this lab has no context windows -> abort -> context fallback
    assert lab.s.calls == ["m1"] and b["mode_used"] == "context"
    assert b["attempts"][0]["fallback_action"] == rs.ABORT


def test_breaker_skips_open_model_and_records_attempt(lab):
    lab.flag("ANAMNESIA_CIRCUIT_BREAKER", "1")
    lab.script({"m1": [("provider_down", 500, None)], "m2": [GOOD], "m3": [GOOD]})
    for _ in range(3):
        ask(lab)
    lab.s.calls.clear()
    b = ask(lab)
    assert lab.s.calls == ["m2"] and b["attempts"][0].get("circuit_open") is True
    assert cb.get_breaker().state("ollama/m1") == cb.OPEN


def test_health_records_real_calls(lab):
    lab.flag("ANAMNESIA_HEALTH", "1")
    lab.script({"m1": [GOOD], "m2": [GOOD], "m3": [GOOD]})
    for _ in range(3):
        ask(lab)
    st = hl.get_tracker().stats("ollama/m1")
    assert st["n"] == 3 and st["verdict"] == "healthy" and st["p95_ms"] is not None


def test_exception_path_still_scrubbed_and_classified_with_flags(lab):
    import httpx
    lab.flag("ANAMNESIA_RETRY", "1")
    lab.script({"m1": [httpx.ReadTimeout("slow")], "m2": [GOOD], "m3": [GOOD]})
    b = ask(lab)
    assert lab.s.calls == ["m1", "m1", "m1", "m2"] and b["attempts"][0]["error_kind"] == "timeout"
