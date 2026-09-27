"""Deterministic pre-processing and deduplication (§15, §16). No AI involved."""
from __future__ import annotations

import hashlib
import re

from app.gateway.token_budget import estimate_tokens, truncate_to_tokens
from app.schemas.models import Candidate

_MULTI_BLANK = re.compile(r"\n{3,}")
_TRAIL_WS = re.compile(r"[ \t]+\n")
_INLINE_WS = re.compile(r"[ \t]{2,}")


def normalize_text(text: str) -> str:
    """Normalization used ONLY for hashing: lowercase, collapse all whitespace."""
    return " ".join(text.lower().split())


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def clean_snippet(text: str) -> str:
    """Remove excessive whitespace while keeping headings and code block structure."""
    out_lines = []
    in_fence = False
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out_lines.append(line.rstrip())
            continue
        out_lines.append(line.rstrip() if in_fence else _INLINE_WS.sub(" ", line).rstrip())
    text = "\n".join(out_lines)
    text = _TRAIL_WS.sub("\n", text)
    return _MULTI_BLANK.sub("\n\n", text).strip()


def preprocess(candidates: list[Candidate], snippet_max_tokens: int) -> list[Candidate]:
    """Clean, drop empty, cap snippet size, compute hash + token estimate."""
    out = []
    for c in candidates:
        snippet = clean_snippet(c.snippet)
        if not snippet or len(snippet.strip("#- \n")) < 3:
            continue
        snippet = truncate_to_tokens(snippet, snippet_max_tokens)
        c.snippet = snippet
        c.content_hash = content_hash(snippet)
        c.token_estimate = estimate_tokens(snippet)
        out.append(c)
    return out


def deduplicate(candidates: list[Candidate], max_per_note: int = 1) -> tuple[list[Candidate], int]:
    """Remove duplicates by content hash and by (source_file, section, snippet);
    keep at most `max_per_note` best-scored candidates per note (§15).

    Returns (unique_candidates_sorted_by_score, removed_count).
    """
    ordered = sorted(candidates, key=lambda c: (-c.score, c.source_file, c.section))
    seen_hash: set[str] = set()
    seen_key: set[tuple[str, str, str]] = set()
    per_note: dict[str, int] = {}
    kept: list[Candidate] = []
    for c in ordered:
        h = c.content_hash or content_hash(c.snippet)
        key = (c.source_file, c.section, normalize_text(c.snippet))
        if h in seen_hash or key in seen_key:
            continue
        if per_note.get(c.source_file, 0) >= max_per_note:
            continue
        seen_hash.add(h)
        seen_key.add(key)
        per_note[c.source_file] = per_note.get(c.source_file, 0) + 1
        kept.append(c)
    return kept, len(candidates) - len(kept)
