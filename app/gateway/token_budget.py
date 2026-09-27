"""Deterministic token estimation and budgeting (§13, §16, §29).

We deliberately avoid provider tokenizers: estimates must be identical for every consumer model.
Heuristic: max(chars/4, words*1.3) — conservative for Portuguese text with accents.
Real provider token counts (when exposed) are recorded separately as model/JEV tokens.
"""
from __future__ import annotations

import math
import re
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
_WORD = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chars = len(text)
    words = len(_WORD.findall(text))
    return max(1, math.ceil(max(chars / 4.0, words * 1.3)))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Cut text so estimate_tokens(result) <= max_tokens, on a line/word boundary when possible."""
    if estimate_tokens(text) <= max_tokens:
        return text
    suffix = " …"

    def finish(cut: str) -> str:
        return cut.rstrip() + suffix

    # Largest prefix whose FINAL form (including the suffix) fits.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(finish(text[:mid])) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    cut = text[:lo]
    # Prefer a boundary, but only if the result still fits (boundary cuts only remove text).
    nl, sp = cut.rfind("\n"), cut.rfind(" ")
    for pos, ratio in ((nl, 0.6), (sp, 0.8)):
        if pos > len(cut) * ratio and estimate_tokens(finish(cut[:pos])) <= max_tokens:
            return finish(cut[:pos])
    return finish(cut) if cut else suffix.strip()


def pack_batches(items: Iterable[T], cost: Callable[[T], int], budget: int, base_cost: int = 0) -> list[list[T]]:
    """Adaptive batching (§13): greedily fill a batch, stop before the budget, start the next one.

    An item larger than the budget on its own gets its own batch (caller must have truncated it).
    """
    batches: list[list[T]] = []
    current: list[T] = []
    used = base_cost
    for item in items:
        c = cost(item)
        if current and used + c > budget:
            batches.append(current)
            current, used = [], base_cost
        current.append(item)
        used += c
    if current:
        batches.append(current)
    return batches


def fit_within(items: Iterable[T], cost: Callable[[T], int], budget: int) -> tuple[list[T], int]:
    """Take items in order while they fit in the budget. Returns (selected, tokens_used)."""
    selected: list[T] = []
    used = 0
    for item in items:
        c = cost(item)
        if used + c > budget:
            continue  # a later, smaller item may still fit
        selected.append(item)
        used += c
    return selected, used
