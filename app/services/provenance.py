"""Provenance, temporality and consistency for the memory delivered to a consumer (§M3).

Three deterministic, zero-token, zero-network facts about a note, all read from its frontmatter:

  TEMPORALITY   `status: arquivado` or `superseded_by`/`substituida_por` means the note is HISTORICAL:
                it records what was true, not what is true. Such a note is demoted in the ranking
                (never promoted) and is only delivered when the query explicitly asks for history.

  PROVENANCE    every delivered source gets one compact line saying WHICH file it came from, what
                kind of note it is, whether it is archived, when it was last touched and which
                project it belongs to. The line is metadata, not authority: CONTEXT_HEADER already
                tells the consumer to treat note content as data, and this line never repeats that
                sentence (the injection flag has its own attribute on the same block).

  CONSISTENCY   two notes that answer the same question can disagree -- the classic case being an
                old decision still marked `ativo` next to the one that replaced it. Inside the FINAL
                candidate set the newer note wins and the older one is demoted and marked, never
                deleted: the vault is read-only for the Gateway and the older note may still be what
                the user actually wants (that is what the history terms are for).

Everything here reads the vault through ObsidianVault (read-only) and nothing else. No model call,
no network, no write.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.gateway.token_budget import estimate_tokens
from app.schemas.models import Candidate
from app.services.near_dup import jaccard, shingles
from app.services.obsidian import ObsidianVault, frontmatter_fields
from app.services.query_fp import fold
from app.services.scope import project_of, slug as project_slug

#: A query containing any of these (accent-folded, substring) is asking about the PAST, so
#: historical notes stop being demoted and are marked instead.
HISTORY_TERMS: tuple[str, ...] = (
    "historico", "historica", "antes", "antigo", "antiga", "versao anterior", "versoes anteriores",
    "por que mudou", "porque mudou", "o que mudou", "mudou", "evolucao", "evoluiu", "descontinuad",
)

HISTORICAL_STATUSES = frozenset({"arquivado", "arquivada", "archived", "obsoleto", "obsoleta"})
SUPERSEDED_KEYS = ("superseded_by", "supersedes", "substituida_por", "substitui", "supersededby")
_UNKNOWN = "?"
_DATE_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
_WS = re.compile(r"\s+")


def wants_history(query: str) -> bool:
    """True when the query asks for history. Accent-insensitive, deterministic, zero cost."""
    if not query:
        return False
    folded = fold(query)
    return any(term in folded for term in HISTORY_TERMS)


def parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    raw = value.strip().strip("'\"")
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        v = _WS.sub(" ", value).strip()
        return v or None
    return None


@dataclass(frozen=True)
class NoteFacts:
    """What a note declares about itself. `None` fields mean "not declared", never "empty"."""

    path: str
    title: str | None = None
    area: str | None = None
    type_: str | None = None
    status: str | None = None
    projeto: str | None = None
    created: date | None = None
    updated: date | None = None
    superseded_by: str | None = None
    has_frontmatter: bool = False

    @property
    def is_archived(self) -> bool:
        return (self.status or "").strip().lower() in HISTORICAL_STATUSES

    @property
    def is_historical(self) -> bool:
        """Historical = superseded by another note, or archived. Both mean "this was true once"."""
        return bool(self.superseded_by) or self.is_archived

    @property
    def touched(self) -> date | None:
        return self.updated or self.created

    def project_slug(self) -> str:
        """Frontmatter `projeto` wins; otherwise the path decides (app/services/scope.py)."""
        if self.projeto:
            return project_slug(self.projeto)
        return project_of(self.path) or "global"

    @classmethod
    def from_text(cls, path: str, text: str) -> "NoteFacts":
        fm = frontmatter_fields(text)
        superseded = None
        for k in SUPERSEDED_KEYS:
            v = _text(fm.get(k))
            if v:
                superseded = v
                break
        return cls(
            path=path,
            title=_text(fm.get("title")),
            area=_text(fm.get("area")),
            type_=_text(fm.get("type")),
            status=_text(fm.get("status")),
            projeto=_text(fm.get("projeto")),
            created=parse_date(fm.get("created")),
            updated=parse_date(fm.get("updated")),
            superseded_by=superseded,
            has_frontmatter=bool(fm),
        )


class ProvenanceIndex:
    """Lazily reads ONE note's frontmatter per delivered file and caches it.

    The delivered context holds at most `model_context_budget` tokens, i.e. a handful of files, so a
    per-file read (frontmatter only, in memory) is cheaper than any index and can never go stale
    inside a request. The instance is dropped whenever the vault fingerprint changes
    (app/gateway/optimizer.py), so a rewritten note is re-read.
    """

    def __init__(self, vault: ObsidianVault):
        self.vault = vault
        self._facts: dict[str, NoteFacts | None] = {}
        self._lines: dict[str, str] = {}

    def facts(self, rel_path: str) -> NoteFacts:
        if rel_path in self._facts:
            cached = self._facts[rel_path]
            return cached if cached is not None else NoteFacts(path=rel_path)
        try:
            text = self.vault.read(rel_path)
        except Exception:  # noqa: BLE001 — a missing/unreadable note must never break a search
            self._facts[rel_path] = None
            return NoteFacts(path=rel_path)
        f = NoteFacts.from_text(rel_path, text)
        self._facts[rel_path] = f
        return f

    def line(self, rel_path: str) -> str:
        """The compact provenance line, cached per file. Short by construction -- see `render`."""
        cached = self._lines.get(rel_path)
        if cached is not None:
            return cached
        f = self.facts(rel_path)
        line = render_provenance(f)
        self._lines[rel_path] = line
        return line

    def marker(self, rel_path: str) -> str:
        """`[histórico]` when the note is archived or superseded, else an empty string."""
        return HISTORICAL_MARKER if self.facts(rel_path).is_historical else ""

    def stats(self) -> dict:
        return {"notes_inspected": len(self._facts), "lines_cached": len(self._lines)}


HISTORICAL_MARKER = "[histórico]"


def render_provenance(f: NoteFacts) -> str:
    """`[fonte: <arquivo> · <type> · <status> · atualizado <YYYY-MM-DD> · projeto <slug>]`

    The file NAME is used, not the full path: the `<note source="...">` attribute on the very same
    block already carries the path, and repeating it would pay for it twice. `?` marks a field the
    note does not declare -- the line never invents a value.
    """
    name = Path(f.path).stem or f.path
    touched = f.touched.isoformat() if f.touched else _UNKNOWN
    return (f"[fonte: {name} · {f.type_ or _UNKNOWN} · {f.status or _UNKNOWN} · "
            f"atualizado {touched} · projeto {f.project_slug()}]")


def provenance_tokens(lines: list[str]) -> int:
    """Measured cost of the provenance layer: `estimate_tokens` of every line actually delivered."""
    return sum(estimate_tokens(line) for line in lines if line)


# -- TEMPORALITY -------------------------------------------------------------------------------

def apply_temporal(cands: list[Candidate], index: ProvenanceIndex | None, history_wanted: bool,
                   demote_factor: float, exclude: bool = False) -> tuple[list[Candidate], dict]:
    """Mark historical notes and, unless the query asked for history, demote or drop them.

    `exclude=False` (the default) only demotes: the note stays available at the tail of the ranking,
    which is what keeps recall intact when a query legitimately needs an old note without using one
    of the history terms. `exclude=True` implements the strict reading -- a historical note is
    delivered ONLY when history was requested. Nothing is ever deleted from the vault either way;
    the decision is per-request and recorded in the run's metrics.
    """
    metrics = {"memory_historical_total": 0, "memory_historical_demoted": 0,
               "memory_historical_excluded": 0, "memory_history_requested": bool(history_wanted)}
    if index is None or not cands:
        return cands, metrics
    kept: list[Candidate] = []
    for c in cands:
        f = index.facts(c.source_file)
        if not f.is_historical:
            kept.append(c)
            continue
        metrics["memory_historical_total"] += 1
        meta = {**(c.meta or {}), "historical": True,
                "note_status": f.status, "superseded_by": f.superseded_by}
        if history_wanted:
            c.meta = meta          # delivered, but visibly marked as history
            kept.append(c)
            continue
        if exclude:
            metrics["memory_historical_excluded"] += 1
            continue
        c.meta = {**meta, "temporal_demoted": True}
        c.score = c.score * demote_factor
        metrics["memory_historical_demoted"] += 1
        kept.append(c)
    return kept, metrics


# -- CONSISTENCY -------------------------------------------------------------------------------

def _title_key(c: Candidate, index: ProvenanceIndex) -> str:
    f = index.facts(c.source_file)
    raw = f.title or c.section.split(" > ")[0] or Path(c.source_file).stem
    return fold(_WS.sub(" ", raw).strip())


def resolve_conflicts(cands: list[Candidate], index: ProvenanceIndex | None, demote_factor: float,
                      overlap: float) -> tuple[list[Candidate], dict]:
    """Flag potentially conflicting notes inside the final set. The newest wins; nothing is dropped.

    Two detectors, both cheap and both deterministic:
      1. same normalized title in two different notes (the classic "old decision still ativo");
      2. high shingle overlap between two different notes whose `updated` dates DIFFER -- same
         subject, different moment. Identical dates are exempt: two sections of the same decision
         written on the same day are not a contradiction, and flagging them would be noise.
    """
    metrics = {"memory_conflicts_detected": 0, "memory_conflict_same_title": 0,
               "memory_conflict_overlap": 0}
    if index is None or len(cands) < 2:
        return cands, metrics

    def newest(c: Candidate):
        f = index.facts(c.source_file)
        return (f.touched or date.min, c.score, c.candidate_id)

    demoted: dict[str, tuple[Candidate, str, str]] = {}

    def demote(older: Candidate, winner: Candidate, reason: str) -> bool:
        if older.source_file == winner.source_file or older.source_file in demoted:
            return False
        f = index.facts(older.source_file)
        older.meta = {**(older.meta or {}), "conflict": {"reason": reason, "with": winner.source_file},
                      "conflict_note_touched": f.touched.isoformat() if f.touched else None}
        older.score = older.score * demote_factor
        demoted[older.source_file] = (older, reason, winner.source_file)
        return True

    by_title: dict[str, list[Candidate]] = {}
    for c in cands:
        by_title.setdefault(_title_key(c, index), []).append(c)
    for group in by_title.values():
        files = {c.source_file for c in group}
        if len(files) < 2:
            continue
        ordered = sorted(group, key=newest, reverse=True)
        winner = ordered[0]
        for c in ordered[1:]:
            if demote(c, winner, "same_title"):
                metrics["memory_conflict_same_title"] += 1

    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.source_file == b.source_file or a.source_file in demoted or b.source_file in demoted:
                continue
            fa, fb = index.facts(a.source_file), index.facts(b.source_file)
            if fa.touched is None or fb.touched is None or fa.touched == fb.touched:
                continue
            overlap_score = jaccard(shingles(a.snippet or "", 5), shingles(b.snippet or "", 5))
            if overlap_score < overlap:
                continue
            older, newer = (a, b) if (fa.touched, a.score) < (fb.touched, b.score) else (b, a)
            if demote(older, newer, f"overlap_{overlap_score:.2f}"):
                metrics["memory_conflict_overlap"] += 1

    metrics["memory_conflicts_detected"] = len(demoted)
    return cands, metrics