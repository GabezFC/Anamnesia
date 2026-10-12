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

INJECTION_SCREEN_VERSION = "inj-screen-v2"  # ANA-036: NFKC + zero-width + homoglyph + base64 + markdown-link views

# High-signal phrases: an explicit attempt to address or override an assistant.
_STRONG = (
    "ignore previous", "ignore all previous", "disregard previous", "disregard all",
    "ignore as instrucoes", "ignore todas as instrucoes", "desconsidere as instrucoes",
    "esqueca as instrucoes", "system message", "system prompt", "developer message",
    "you must now", "voce deve agora", "a partir de agora voce", "from now on you",
    "act as", "aja como", "pretend to be", "finja ser", "new instructions",
    "novas instrucoes", "override", "jailbreak", "do not tell", "nao conte ao usuario",
    "reveal your", "revele seu", "print your instructions", "repeat the above",
    # ANA-036: paraphrases / indirect phrasing seen in the red-team corpus
    "disregard the earlier", "disregard any prior", "forget everything", "forget your instructions",
    "forget all prior", "ignore the rules above", "ignore your guidelines", "ignore prior",
    "ignore o que foi dito", "ignore tudo acima", "ignore tudo o que", "desconsidere tudo",
    "desconsidere o que", "esqueca tudo", "esqueca o que", "nao siga as regras", "deixe de lado as",
    "ignorar as instrucoes", "your real task", "sua verdadeira tarefa", "your new task",
    "sua nova tarefa", "bypass", "developer mode", "modo desenvolvedor", "dan mode",
    "as an ai without", "sem restricoes", "without restrictions", "do anything now",
    "exfiltrate", "exfiltre", "send the contents", "envie o conteudo", "instead, ", "em vez disso, ",
    "mostre seu prompt", "show your prompt", "initial prompt", "prompt inicial", "regras acima",
    "reveal the secret", "revele o segredo", "revele a chave", "reveal the key", "api key to",
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


# ---- ANA-036: input normalisation -------------------------------------------------------------
# Visible-lookalike letters (Cyrillic/Greek/fullwidth survive NFKC only for fullwidth). Map the common
# Latin lookalikes so "іgnore" (Cyrillic i) or "ѕystem" reach the same phrases as plain ASCII.
_HOMOGLYPHS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s",
    "ԁ": "d", "һ": "h", "ӏ": "l", "ո": "n", "ѵ": "v", "ɡ": "g", "к": "k", "м": "m", "т": "t", "в": "b",
    "н": "h", "А": "a", "В": "b", "Е": "e", "К": "k", "М": "m", "Н": "h", "О": "o", "Р": "p", "С": "c",
    "Т": "t", "Х": "x", "І": "i", "Ј": "j", "Ѕ": "s",
    "α": "a", "ο": "o", "ρ": "p", "ν": "v", "ι": "i", "κ": "k", "τ": "t", "υ": "u", "χ": "x",
    "Α": "a", "Β": "b", "Ε": "e", "Ι": "i", "Κ": "k", "Μ": "m", "Ν": "n", "Ο": "o", "Ρ": "p",
    "Τ": "t", "Χ": "x", "Υ": "y", "Ζ": "z",
})
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u206a-\u206f\ufeff\u00ad\u180e]")
_B64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
_MD_LINK = re.compile(r"!?\[([^\]]*)\]\(\s*<?([^)\s>]*)>?(?:\s+\"([^\"]*)\")?\s*\)")
MAX_B64_DECODES = 8


def _unescape(s: str) -> str:
    from urllib.parse import unquote
    try:
        return unquote(s)
    except Exception:  # noqa: BLE001
        return s


def normalized_views(text: str) -> list[str]:
    """ANA-036: the text as the model would 'read' it. Returns [normalised text, *decoded payloads].

    NFKC (fullwidth, ligatures, compat forms), zero-width/bidi removal, Cyrillic/Greek homoglyph
    folding, base64 blobs decoded (up to MAX_B64_DECODES, printable UTF-8 only) and markdown link
    text/target/title unrolled (a link title or URL-encoded target hides instructions from a human
    reader but not from the model). Deterministic, zero tokens."""
    import base64
    import binascii
    import unicodedata
    t = unicodedata.normalize("NFKC", str(text))
    t = _INVISIBLE.sub("", t)
    t = t.translate(_HOMOGLYPHS)
    views = [t]
    extra: list[str] = []
    for m in _MD_LINK.finditer(t):
        extra.append(" ".join(x for x in (m.group(1), _unescape(m.group(2) or "").replace("-", " ").replace("_", " "),
                                          m.group(3) or "") if x))
    for n, m in enumerate(_B64.finditer(t)):
        if n >= MAX_B64_DECODES:
            break
        blob = m.group(0)
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
            dec = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if dec and sum(ch.isprintable() or ch in "\n	" for ch in dec) / len(dec) > 0.9:
            extra.append(dec)
    if extra:
        views.append("\n".join(extra))
    return views


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
    views = normalized_views(text)
    t = fold(views[0])
    decoded = fold(views[1]) if len(views) > 1 else ""
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
    if decoded:  # hidden payload (base64 / link title / url): any strong hit there is decisive
        hid = [p for p in _STRONG if p in decoded] or ([p for p in _WEAK if p in decoded and "instruc" in p]
                                                       if _IMPERATIVE.search(decoded) else [])
        for p in hid:
            signals.append(f"hidden:{p}")
            score += 0.5
        if not hid and _IMPERATIVE.search(decoded):
            signals.append("hidden:imperative")
            score += 0.3
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
