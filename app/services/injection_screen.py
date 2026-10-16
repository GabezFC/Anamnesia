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

# ANAM-010: patterns are regexes with WORD BOUNDARIES, matched on the folded text (NFKC + casefold +
# zero-width removal + diacritics stripped), so "override" no longer fires inside "overrides_json" and
# "act as" no longer fires on "a transaction acts as a unit". Bare technical vocabulary (override,
# bypass, system prompt, act as) is NOT strong on its own; it needs an attack-shaped context.
_ADDR = r"(?:all|any|every|your|my|todas?|quaisquer|suas?|seus?|as|os|essas?|esses?|aquelas?)"
_NOUN_EN = r"(?:instructions?|rules|guidelines?|prompts?|directives?|guidance|constraints|policies)"
_NOUN_PT = r"(?:instrucoes|instrucao|regras|diretrizes|orientacoes|prompts?|comandos|ordens|politicas)"
_QUAL_EN = r"(?:previous|prior|earlier|above|preceding|former)"
_QUAL_PT = r"(?:anteriores|anterior|acima|previas|passadas|anteriormente)"
_VERB_EN = r"(?:ignore|disregard|forget|discard|abandon|override|overrule)"
_VERB_PT = (r"(?:ignor(?:e|a|ar)|desconsider(?:e|a|ar)|descart(?:e|ar)|esquec(?:a|er)|abandon(?:e|ar)|"
            r"anul(?:e|ar)|substitu(?:a|ir)|sobrescrev(?:a|er)|deixe de lado|nao siga|nao obedeca)")
_STRONG_RX: tuple[tuple[str, str], ...] = (
    ("override_en", rf"\b{_VERB_EN}\s+(?:\w+\s+){{0,3}}?{_NOUN_EN}\s+{_QUAL_EN}\b"),
    ("override_en_addr", rf"\b{_VERB_EN}\s+(?:{_ADDR}\s+)+(?:{_QUAL_EN}\s+)?{_NOUN_EN}\b"),
    ("override_en_prev", rf"\b{_VERB_EN}\s+(?:\w+\s+){{0,2}}?{_QUAL_EN}\s+(?:\w+\s+){{0,2}}?{_NOUN_EN}\b"),
    ("override_en_above", rf"\b(?:ignore|disregard|forget)\s+(?:the |all )?(?:rules|everything)\s+{_QUAL_EN}\b"),
    ("override_pt", rf"\b{_VERB_PT}\s+(?:\w+\s+){{0,3}}?{_NOUN_PT}\s+{_QUAL_PT}\b"),
    ("override_pt_addr", rf"\b{_VERB_PT}\s+(?:{_ADDR}\s+)+(?:\w+\s+)?{_NOUN_PT}\b"),
    ("override_pt_prev", rf"\b{_VERB_PT}\s+(?:\w+\s+){{0,2}}?{_QUAL_PT}\b"),
    ("forget_all", r"\bforget\s+(?:everything|all (?:prior|previous|of that))\b"),
    ("esqueca_tudo", r"\b(?:esqueca|esquecer|ignore|ignorar|desconsidere|desconsiderar)\s+(?:tudo|o que (?:foi|esta))\b"),
    ("regras_acima", r"\b(?:ignore|ignorar|desconsidere|siga)\s+(?:as )?regras acima\b"),
    ("new_instructions", r"\b(?:new instructions|novas instrucoes)\s*:"),
    ("from_now_on", r"\b(?:from now on,? you(?:'?re| are| must| will)?|a partir de agora,? (?:voce|tu)\b)"),
    ("must_now", r"\b(?:you must now|you will now|voce deve agora|voce agora (?:e|sera))\b"),
    ("act_as_role", r"\b(?:act as|aja como|atue como|pretend to be|pretend you are|finja (?:ser|que))\s+(?:an? |um |uma |o |a |if )?"
                    r"(?:unrestricted|jailbroken|root|admin\w*|administrador\w*|dan\b|developer|desenvolvedor|evil|malicious|"
                    r"different|new |outro|novo|hacker|my |meu |sem )"),
    ("prompt_exfil", r"\b(?:reveal|show|print|repeat|output|display|leak|dump|revele|mostre|exiba|imprima|repita|vaze)\s+"
                     r"(?:me |us )?(?:(?:your|the|seu|sua|o|a|todo o)\s+)?(?:\w+\s+)?"
                     r"(?:system prompt|initial prompt|prompt inicial|prompt do sistema|system message|developer message|"
                     r"instructions|instrucoes)\b"),
    ("reveal_secret", r"\b(?:reveal (?:your|the) (?:secret|key|password|token|api key|credentials?)|"
                      r"revele (?:o segredo|a chave|a senha|o token|suas credenciais))\b"),
    ("exfiltrate", r"\bexfiltrat\w*|\bexfiltre\w*"),
    ("send_contents", r"\b(?:send|post|upload|email|forward) the contents? of\b|\benvie o conteudo d[eoa]\b"),
    ("api_key_to", r"\bapi key to\b"),
    ("jailbreak", r"\bjailbreak(?:ing|ed)?\b(?! (?:detection|prevention|test|tests|benchmark|research|paper|resistance))"),
    ("dan_mode", r"\b(?:dan mode|do anything now|developer mode enabled|modo desenvolvedor ativado)\b"),
    ("no_restrictions", r"\b(?:as an ai without|(?:you|voce|agente|assistente|ai) (?:are |is |esta |fica |ficara |sera )?(?:now )?(?:sem restricoes|without (?:any )?(?:restrictions|limits|filters)))\b"),
    ("hide_from_user", r"\b(?:do not tell|don't tell|never tell|nao conte|nao diga|nao informe|nao avise)\s+(?:to )?(?:the )?(?:ao |o )?(?:user|usuario)\b"),
    ("bypass_safety", r"\bbypass(?:ing)?\s+(?:\w+\s+){0,2}?(?:safety|restrictions|filters?|guardrails|guidelines|rules|moderation|security)\b"),
    ("your_real_task", r"\b(?:your (?:real|new|actual) task|sua (?:verdadeira|nova|real) tarefa)\b"),
    ("instead_do", r"\b(?:instead|em vez disso),\s*(?:you |voce )?(?:reveal|print|output|send|ignore|execute|run|revele|envie)\b"),
    ("role_marker", r"<\|im_start\|>\s*system|^\s*system\s*:\s*you (?:are|must)\b"),
)
_STRONG_COMPILED = tuple((n, re.compile(rx, re.M)) for n, rx in _STRONG_RX)
# Weaker markers: role names and prompt vocabulary. Individually harmless (this vault documents
# agents for a living), which is exactly why they only count as evidence in combination.
_WEAK_RX: tuple[tuple[str, str], ...] = (
    ("assistant:", r"(?<!\w)assistant:"), ("user:", r"(?<!\w)user:"), ("system:", r"(?<!\w)system:"),
    ('"role"', r'"role"'), ("'role'", r"'role'"), ("role:", r"(?<!\w)role:"),
    ("<|im_start|>", r"<\|im_start\|>"), ("[inst]", r"\[inst\]"),
    ("prompt injection", r"\bprompt[- ]injection\b"), ("system prompt", r"\bsystem prompt\b"),
    ("system message", r"\bsystem message\b"), ("developer message", r"\bdeveloper message\b"),
    ("instruction", r"\binstructions?\b"), ("instrucao", r"\binstrucao\b"), ("instrucoes", r"\binstrucoes\b"),
    ("you must", r"\byou must\b"), ("you should always", r"\byou should always\b"),
    ("obedeca", r"\bobedeca\b"), ("obey", r"\bobey\b"), ("comando ao agente", r"\bcomando ao agente\b"),
    ("jailbreak", r"\bjailbreak\w*"), ("override", r"\boverride\b"),
)
_WEAK_COMPILED = tuple((n, re.compile(rx)) for n, rx in _WEAK_RX)
_IMPERATIVE = re.compile(
    r"\b(ignore|disregard|forget|reveal|output|print|execute|run|delete|send|email|transfer|"
    r"ignora|esqueca|abandone|descarte|desconsidere|revele|envie|apague|responda apenas)\b")


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


def _prep(text: str) -> str:
    """casefold + diacritics stripped + whitespace collapsed (NFKC/zero-width already done upstream)."""
    return re.sub(r"\s+", " ", fold(str(text).casefold())).strip()


def screen(text: str) -> Screen:
    """Lexical pre-screen of one candidate snippet. Deterministic, zero tokens."""
    if not text:
        return Screen(False, 0.0, ())
    views = normalized_views(text)
    t = _prep(views[0])
    decoded = _prep(views[1]) if len(views) > 1 else ""
    signals: list[str] = []
    score = 0.0
    for n, rx in _STRONG_COMPILED:
        if rx.search(t):
            signals.append(f"strong:{n}")
            score += 0.5
    weak_hits = [n for n, rx in _WEAK_COMPILED if rx.search(t)]
    for p in weak_hits:
        signals.append(f"weak:{p}")
    score += 0.15 * len(weak_hits)
    if _IMPERATIVE.search(t):
        signals.append("imperative")
        score += 0.15
    # Second person addressed to a machine is the shape of an instruction, not of documentation.
    if re.search(r"\b(you|voce|voces)\b", t) and weak_hits:
        signals.append("second_person+prompt_vocab")
        score += 0.2
    if decoded:  # hidden payload (base64 / link title / url): any strong hit there is decisive
        hid = [n for n, rx in _STRONG_COMPILED if rx.search(decoded)] or (
            [n for n, rx in _WEAK_COMPILED if "instruc" in n and rx.search(decoded)]
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
