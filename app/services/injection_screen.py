"""Local injection pre-screen (§15) — decides WHO gets an injection question, never the verdict.

WHAT THIS IS NOT
----------------
This is not a security detector and it must never be used as one. The JEV strict-mode question is
the detector. This module only answers a cheaper question: "is it plausible that this candidate
contains manipulation instructions?" — so that in strict mode we can stop paying for an injection
question on the ~90% of candidates where nothing remotely resembles an instruction.

Two forces are in tension and only one of them is cheap to get wrong:
  - a FALSE NEGATIVE here means a manipulative note is never asked about -> security hole.
  - a FALSE POSITIVE here means we pay one extra question -> a few hundred tokens.
So the screen is deliberately over-inclusive: any imperative-at-an-assistant vocabulary, any role
marker, any "instructions" phrasing, and anything that merely mentions prompts/agents/LLMs is
suspicious. The benign-documentation case (a note ABOUT prompt injection) is therefore also flagged,
and that is the correct trade: it costs tokens, not safety.

GATING POLICY
-------------
`should_ask_injection` combines this screen with the relevance verdict (§15): a candidate that the
judge already DROPped is never reaching the consumer model, so asking whether it contains an
injection is paying to secure something we discarded. That gate is the real saving; the lexical
screen is the secondary one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.query_fp import fold

INJECTION_SCREEN_VERSION = "inj-screen-v1"

# High-signal phrases: an explicit attempt to address or override an assistant.
_STRONG = (
    "ignore previous", "ignore all previous", "disregard previous", "disregard all",
    "ignore as instrucoes", "ignore todas as instrucoes", "desconsidere as instrucoes",
    "esqueca as instrucoes", "system message", "system prompt", "developer message",
    "you must now", "voce deve agora", "a partir de agora voce", "from now on you",
    "act as", "aja como", "pretend to be", "finja ser", "new instructions",
    "novas instrucoes", "override", "jailbreak", "do not tell", "nao conte ao usuario",
    "reveal your", "revele seu", "print your instructions", "repeat the above",
)
# Weaker markers: role names and prompt vocabulary. Individually harmless (this vault documents
# agents for a living), which is exactly why they only count as evidence in combination.
_WEAK = (
    "assistant:", "user:", "system:", "\"role\"", "'role'", "role:", "<|im_start|>", "[inst]",
    "prompt injection", "prompt-injection", "instruction", "instrucao", "instrucoes",
    "you must", "you should always", "obedeca", "obey", "comando ao agente",
)
_IMPERATIVE = re.compile(
    r"\b(ignore|disregard|forget|reveal|output|print|execute|run|delete|send|email|transfer|"
    r"ignora|ignore|esqueca|revele|execute|envie|apague|responda apenas)\b")


@dataclass(frozen=True)
class Screen:
    suspicious: bool
    score: float               # 0..1 heuristic confidence, for metrics only — never a verdict
    signals: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"suspicious": self.suspicious, "screen_score": self.score,
                "signals": list(self.signals)}


def screen(text: str) -> Screen:
    """Lexical pre-screen of one candidate snippet. Deterministic, zero tokens."""
    if not text:
        return Screen(False, 0.0, ())
    t = fold(text)
    signals: list[str] = []
    score = 0.0
    for p in _STRONG:
        if p in t:
            signals.append(f"strong:{p}")
            score += 0.5
    weak_hits = [p for p in _WEAK if p in t]
    for p in weak_hits:
        signals.append(f"weak:{p}")
    score += 0.15 * len(weak_hits)
    if _IMPERATIVE.search(t):
        signals.append("imperative")
        score += 0.15
    # Second person addressed to a machine is the shape of an instruction, not of documentation.
    if re.search(r"\b(you|voce|vocês|voces)\b", t) and weak_hits:
        signals.append("second_person+prompt_vocab")
        score += 0.2
    score = min(1.0, score)
    # Over-inclusive on purpose: ANY signal at all buys the candidate an injection question.
    return Screen(bool(signals), round(score, 3), tuple(signals[:8]))


def should_ask_injection(text: str, relevance: float | None, keep_threshold: float,
                         review_threshold: float, *, gate_on_relevance: bool = True,
                         screen_enabled: bool = True) -> tuple[bool, str]:
    """Decide whether this candidate needs the paid injection question. Returns (ask, reason).

    Ordering matters and follows §15:
      1. relevance unknown  -> ask (we cannot reason about a candidate we have not judged)
      2. relevance < review -> DROP, never reaches the consumer -> do not ask
      3. lexical screen clean -> do not ask
      4. otherwise -> ask
    """
    if relevance is None:
        return True, "unjudged"
    if gate_on_relevance and relevance < review_threshold:
        return False, "dropped_by_relevance"
    if not screen_enabled:
        return True, "screen_disabled"
    s = screen(text)
    if s.suspicious:
        return True, f"screen_hit:{s.signals[0] if s.signals else 'unknown'}"
    return False, "screen_clean"
