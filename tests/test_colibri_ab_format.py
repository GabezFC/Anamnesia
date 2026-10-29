"""Colibri aceita o formato choice A/B da Laya (offline, sem rede) — H1 2026-10-24."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from app.services import laya_decider as L
from app.services.colibri import ColibriJudgeBackend, ColibriUnavailable
from config.colibri import ColibriConfig


class FakeClient:
    def __init__(self, resp):
        self.resp, self.sent = resp, None

    def system_one(self, state, questions, model):
        self.sent = questions
        return self.resp


def _backend(resp):
    fc = FakeClient(resp)
    return ColibriJudgeBackend(ColibriConfig(enabled=True), client_factory=lambda *a: fc), fc


def _resp(nouls=None, choices=None, scores=None):
    return NS(nouls=nouls or {}, choices=choices or {}, scores=scores or {}, model="m",
              usage=NS(input_tokens=5, output_tokens=1))


def test_laya_relevance_choice_serializes_without_network():
    b, fc = _backend(_resp(choices={"rel": NS(probabilities={"A": 0.7, "B": 0.2, "C": 0.1})}))
    answers, usage, model = b.evaluate("s", {"rel": L.Q_RELEVANCE})
    assert answers == {"rel": pytest.approx(0.7)} and usage["input_tokens"] == 5
    wire = fc.sent["rel"].model_dump()
    assert wire["type"] == "choice" and set(wire["criteria"]) == {"A", "B", "C"}


def test_laya_ab_helper_roundtrip():
    q = L._ab("Is it relevant?", "yes desc", "no desc")
    b, _ = _backend(_resp(choices={"x": NS(probabilities={"A": 0.4, "B": 0.6})}))
    assert b.evaluate("s", {"x": q})[0]["x"] == pytest.approx(0.4)


def test_noul_still_works_and_mixed():
    b, fc = _backend(_resp(nouls={"n": NS(noul=0.3)}, choices={"c": NS(probabilities={"A": 0.9, "B": 0.1})}))
    qs = {"n": {"type": "noul", "instructions": "i", "criteria": {"true": "t", "false": "f"}},
          "c": L._ab("i", "a", "b")}
    ans = b.evaluate("s", qs)[0]
    assert ans == {"n": pytest.approx(0.3), "c": pytest.approx(0.9)}


def test_choice_without_A_is_explicit_error():
    b, _ = _backend(_resp(choices={"c": NS(probabilities={"X": 1.0})}))
    with pytest.raises(ColibriUnavailable):
        b.evaluate("s", {"c": L._ab("i", "a", "b")})


def test_unknown_type_and_empty_choice_rejected():
    with pytest.raises(ValueError):
        ColibriJudgeBackend.build_question({"type": "foo"})
    with pytest.raises(ValueError):
        ColibriJudgeBackend.build_question({"type": "choice", "instructions": "i"})
