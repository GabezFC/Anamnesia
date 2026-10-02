"""Memory audit — a READ-ONLY inventory of everything the persistent memory actually holds.

The vault (Obsidian) is the source of truth and the Gateway never writes to it, so there is no
"database size" to report: what matters is whether the stored memory is USABLE. This module answers
that with counts only — no note content is ever returned, printed or persisted, and it reuses the
same frontmatter semantics as the retrieval path (app/services/provenance.py) so the audit can never
disagree with what a search would see.

What it measures (all deterministic, zero network, zero tokens):
  inventory       notes by area/projeto/type/status, bytes and estimated tokens (total and mean)
  growth          notes created and updated per day, from the frontmatter dates
  duplication     exact (sha256 of the note body) and near (app/services/near_dup.py)
  graph health    orphans (no inbound wikilink) and broken wikilinks
  metadata health notes without frontmatter, and notes missing a declared field
  temporality     archived / superseded notes, and active notes untouched for more than N days
  consistency     candidates for conflict: same title among active notes, or a note that cites
                  another as superseded
  boilerplate     sections repeated across notes (the "## Relacionadas" family)
  lifecycle       hot / warm / cold, from the sources actually DELIVERED, read out of benchmark.db
                  with a `mode=ro` connection (never written, never locked)

Results are cached per `vault.fingerprint()` (app/services/obsidian.py) — the same cheap change
detector the optimization layer uses — so a repeated audit costs one stat pass, not one vault scan.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.gateway.token_budget import estimate_tokens
from app.services.near_dup import hamming, jaccard, shingles, similarity, simhash
from app.services.obsidian import (ObsidianVault, Section, frontmatter_fields, split_frontmatter,
                                     split_sections)
from app.services.provenance import HISTORICAL_MARKER, NoteFacts, parse_date, render_provenance
from app.services.query_fp import fold
from app.services.scope import project_of

DEFAULT_INACTIVE_DAYS = 90
DEFAULT_NEAR_DUP_THRESHOLD = 0.92
#: Fields the vault convention says every note declares (docs/PERSISTENT_MEMORY_ARCHITECTURE.md).
REQUIRED_FIELDS = ("id", "title", "area", "type", "tags", "status", "created", "updated")

_WLINK = re.compile(r"\[\[([^\[\]]*?)\]\]")
_FENCE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")
_MARKUP = re.compile(r"[`*_>#\[\](){}|\-—–:;,.!?\"'/\\]+")
_NUMBER = re.compile(r"\d+")
_WS = re.compile(r"\s+")
#: Same archive vocabulary the retrieval path uses (app/services/provenance.py).
_ARCHIVED = frozenset({"arquivado", "arquivada", "archived", "obsoleto", "obsoleta"})


def _norm(text: str) -> str:
    """STRUCTURAL normalization (markup, numbers, case and spacing dropped).

    Only for *similarity* signals -- near-duplicates and repeated sections. It is deliberately too
    aggressive to decide that two notes are the same: see `body_key` for the exact-duplicate rule.
    """
    return _WS.sub(" ", _NUMBER.sub(" ", _MARKUP.sub(" ", text)).strip().lower())


_H1 = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)


def strip_title_echo(body: str, title: str | None) -> str:
    """Drop a leading `# <title>` heading when it just repeats the declared title.

    A note usually writes the title twice -- once in `title:` and once as the H1. That echo is
    metadata, not content: hashing it would report two copies of the same note as different
    whenever their titles differ. Any other heading stays, so real content differences survive.
    """
    if not title:
        return body
    m = _H1.match(body)
    if m and fold(m.group(1)) == fold(title):
        return body[m.end():]
    return body


def body_key(body: str) -> str:
    """Exact-duplicate key: the body with whitespace and case normalized and NOTHING else removed.

    Numbers, punctuation, markup and accents stay in the key, so two notes that differ only by a
    date, an id or a version are reported as near-duplicates (worth reviewing) and never as exact
    duplicates (worth deleting).
    """
    return _WS.sub(" ", body.strip()).casefold()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


@dataclass
class AuditNote:
    rel_path: str
    title: str | None = None
    area: str | None = None
    type_: str | None = None
    status: str | None = None
    tags: list[str] = field(default_factory=list)
    projeto: str | None = None
    created: date | None = None
    updated: date | None = None
    superseded_by: str | None = None
    graph_node: str | None = None
    bytes: int = 0
    tokens_est: int = 0
    content_hash: str = ""
    has_frontmatter: bool = False
    missing_fields: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    project_slug: str | None = None

    @property
    def is_archived(self) -> bool:
        return (self.status or "").strip().lower() in _ARCHIVED

    @property
    def is_historical(self) -> bool:
        return bool(self.superseded_by) or self.is_archived

    @property
    def touched(self) -> date | None:
        return self.updated or self.created


@dataclass
class MemoryUsage:
    """Retrieval frequency of each note, from delivered sources in benchmark.db (read-only)."""

    hot: int = 0
    warm: int = 0
    cold: int = 0
    hot_top: list[tuple[str, int]] = field(default_factory=list)
    warm_top: list[tuple[str, int]] = field(default_factory=list)
    cold_top: list[tuple[str, int]] = field(default_factory=list)
    runs_scanned: int = 0
    deliveries: int = 0
    db_path: str | None = None
    db_error: str | None = None


@dataclass
class MemoryAuditSummary:
    vault_notes: int
    notes_scanned: int
    by_area: dict[str, int]
    by_projeto: dict[str, int]
    by_type: dict[str, int]
    by_status: dict[str, int]
    bytes_total: int
    bytes_avg: float
    tokens_total: int
    tokens_avg: float
    provenance_tokens_total: int
    provenance_tokens_mean: float
    created_per_day: dict[str, int]
    updated_per_day: dict[str, int]
    dup_exact: int
    dup_exact_groups: int
    dup_near_groups: int
    orphan_count: int
    wikilinks_total: int
    wikilinks_broken_count: int
    notes_without_fm: int
    notes_missing_fields: int
    missing_fields_by_key: dict[str, int]
    inactive_days: int
    inactive_gt_n: int
    archived_count: int
    superseded_count: int
    historical_count: int
    conflicts: int
    conflicts_same_title: int
    conflicts_superseded: int
    hot_count: int
    warm_count: int
    cold_count: int
    repeated_sections: int
    notes_with_repeated_sections: int
    repeated_section_tokens: int
    repeated_section_token_share: float
    db_runs_scanned: int
    db_deliveries: int
    memory_conflicts_detected: int
    memory_historical_demoted: int


@dataclass
class MemoryAuditReport:
    vault: str
    vault_fingerprint: tuple
    generated_at: str
    scan_ms: float
    cached: bool
    summary: MemoryAuditSummary
    dup_exact: list[list[str]]
    dup_near: list[list[str]]
    orphans: list[str]
    wikilinks_broken: dict[str, list[str]]
    notes_without_frontmatter: list[str]
    notes_missing_fields: dict[str, list[str]]
    inactive: list[str]
    archived: list[str]
    superseded: list[str]
    conflicts: list[list[str]]
    repeated_headings: list[tuple[str, int]]
    usage: MemoryUsage
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def counts_only(self) -> dict[str, Any]:
        """Everything except the per-file candidate lists. Used for the persisted report: it proves
        the audit on a REAL vault without copying a single line of anybody's notes."""
        return {"vault": self.vault, "vault_fingerprint": list(self.vault_fingerprint),
                "generated_at": self.generated_at, "scan_ms": self.scan_ms,
                "parameters": self.parameters, "summary": asdict(self.summary),
                "usage_counts": {"hot": self.usage.hot, "warm": self.usage.warm,
                                 "cold": self.usage.cold, "runs_scanned": self.usage.runs_scanned,
                                 "deliveries": self.usage.deliveries, "db_path": self.usage.db_path,
                                 "db_error": self.usage.db_error},
                "note_content_included": False}


# -- retrieval frequency (benchmark.db, read-only) ----------------------------------------------

def delivery_counts(db_path: Path | str | None, max_runs: int = 0) -> tuple[dict[str, int], int, int]:
    """How many times each vault file was DELIVERED, counted from `runs.sources_json`.

    Opens the database with `mode=ro`: sqlite itself refuses the write, so an audit can never lock
    or modify the benchmark store. Returns ({file: deliveries}, rows scanned, total deliveries).
    """
    if not db_path:
        return {}, 0, 0
    p = Path(db_path)
    if not p.is_file():
        raise FileNotFoundError(f"benchmark.db não encontrado: {p}")
    uri = f"file:{p.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        sql = ("SELECT sources_json FROM runs WHERE sources_json IS NOT NULL AND sources_json <> ''"
               + (" ORDER BY created_at DESC LIMIT ?" if max_runs else ""))
        cur = con.execute(sql, (max_runs,) if max_runs else ())
        counts: dict[str, int] = {}
        rows = deliveries = 0
        while True:
            batch = cur.fetchmany(500)
            if not batch:
                break
            for (raw,) in batch:
                rows += 1
                try:
                    srcs = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(srcs, list):
                    continue
                for s in srcs:
                    f = s.get("file") if isinstance(s, dict) else None
                    if f:
                        counts[f] = counts.get(f, 0) + 1
                        deliveries += 1
        return counts, rows, deliveries
    finally:
        con.close()


# -- the auditor ---------------------------------------------------------------------------------

class MemoryAuditor:
    def __init__(self, vault_path: Path | str, db_path: Path | str | None = None,
                 excluded_dirs: tuple[str, ...] | None = None):
        # `excluded_dirs=None` keeps ObsidianVault's own defaults. Callers that already hold a
        # RetrievalConfig (CLI, REST route) pass ITS exclusions, so the audit counts exactly the
        # notes a search can reach -- otherwise `99-Templates/` would inflate every count.
        self.vault = (ObsidianVault(Path(vault_path), excluded_dirs) if excluded_dirs
                      else ObsidianVault(Path(vault_path)))
        self.db_path = Path(db_path) if db_path else None

    # -- note loading -----------------------------------------------------------------------------
    def load_notes(self) -> list[tuple[AuditNote, str, list[Section]]]:
        """(note, raw text, sections) for every markdown file. The sections are returned so the
        boilerplate scan reuses one parse instead of splitting every note three times. The body hash
        covers the BODY only, so two notes that differ only in `updated` are not exact duplicates."""
        out: list[tuple[AuditNote, str, list[Section]]] = []
        for rel in self.vault.list_markdown():
            try:
                text = self.vault.read(rel)
            except Exception:  # noqa: BLE001 — an unreadable file is skipped, never fatal
                continue
            fm_block, body = split_frontmatter(text)
            fields = frontmatter_fields(text)
            facts = NoteFacts.from_text(rel, text)
            tags = fields.get("tags")
            graph_node = fields.get("graph_node")
            missing = [k for k in REQUIRED_FIELDS if k not in fields] if fm_block else []
            sections = split_sections(text)
            out.append((AuditNote(
                rel_path=rel, title=facts.title, area=facts.area, type_=facts.type_,
                status=facts.status, tags=tags if isinstance(tags, list) else [],
                projeto=facts.projeto, created=facts.created, updated=facts.updated,
                superseded_by=facts.superseded_by,
                graph_node=graph_node if isinstance(graph_node, str) else None,
                bytes=len(text.encode("utf-8", errors="replace")), tokens_est=estimate_tokens(text),
                content_hash=(_sha256(body_key(strip_title_echo(body, facts.title)))
                              if body_key(strip_title_echo(body, facts.title)) else _sha256(rel)),
                has_frontmatter=bool(fm_block), missing_fields=missing,
                sections=[],
                project_slug=project_of(rel, facts.projeto),
            ), text, sections))
        return out

    # -- links -----------------------------------------------------------------------------------
    @staticmethod
    def _wikilinks(body: str) -> list[str]:
        return [m.split("|")[0].split("#")[0].strip()
                for m in _WLINK.findall(_FENCE.sub(" ", body)) if m.strip()]

    def _link_graph(self, loaded: list[tuple[AuditNote, str, list[Section]]]
                    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """(outbound note paths per note, broken link targets per note).

        Resolution is the two forms Obsidian accepts and nothing more: an exact relative path (with
        or without `.md`) or a bare file stem, both case-insensitive. An ambiguous stem resolves to
        EVERY match, exactly as Obsidian does -- treating it as broken would report a link the vault
        itself follows. The OUTBOUND list holds note paths, not link text, so the orphan count is a
        real backlink count.
        """
        paths = {n.rel_path.lower(): n.rel_path for n, _, _ in loaded}
        stems: dict[str, list[str]] = {}
        for n, _, _ in loaded:
            stems.setdefault(Path(n.rel_path).stem.lower(), []).append(n.rel_path)
        resolved: dict[str, list[str]] = {}
        broken: dict[str, list[str]] = {}
        for note, text, _sections in loaded:
            _, body = split_frontmatter(text)
            ok: list[str] = []
            bad: list[str] = []
            for target in self._wikilinks(body):
                t = target.replace("\\", "/").strip()
                hits: list[str] = []
                if "/" in t:
                    tl = t.lower()
                    if tl in paths:
                        hits = [paths[tl]]
                    elif tl + ".md" in paths:
                        hits = [paths[tl + ".md"]]
                elif Path(t).stem.lower() in stems:
                    hits = list(stems[Path(t).stem.lower()])
                elif t.lower() in paths:
                    hits = [paths[t.lower()]]
                if hits:
                    ok.extend(h for h in hits if h != note.rel_path)
                else:
                    bad.append(target)
            resolved[note.rel_path] = sorted(set(ok))
            if bad:
                broken[note.rel_path] = bad
        return resolved, broken

    # -- near-duplicates ---------------------------------------------------------------------------
    @staticmethod
    def _near_dup_groups(loaded: list[tuple[AuditNote, str, list[Section]]], threshold: float,
                         bands: int = 8) -> list[list[str]]:
        """Near-duplicate groups over the whole vault.

        All pairs are impossible on a real vault (the O(n²) scan of the first version cost minutes
        on a few hundred notes), so pairs are pre-gated by the SAME banded-simhash bucketing the
        candidate clusterer uses (app/services/near_dup.py) and then confirmed with the
        length-invariant sequence similarity. Deterministic: bands, thresholds and the arbiter are all
        fixed, so two runs on the same vault return the same groups.
        """
        n = len(loaded)
        if n < 2:
            return []
        texts = [t for _, t, _ in loaded]
        sigs = [simhash(t) for t in texts]
        # Shingle sets are computed ONCE per note: recomputing them per pair was ~90% of the scan
        # (13934 tokenizations of the same 520 notes, measured 2026-10-02).
        shs = [shingles(t, 4) for t in texts]
        width = max(1, 64 // bands)
        buckets: dict[tuple[int, int], list[int]] = {}
        for i, sig in enumerate(sigs):
            for b in range(bands):
                buckets.setdefault((b, (sig >> (b * width)) & ((1 << width) - 1)), []).append(i)
        gate = max(0.2, threshold - 0.35)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        compared = 0
        for idxs in buckets.values():
            if len(idxs) < 2 or len(idxs) > 64:
                continue
            for p in range(len(idxs)):
                for q in range(p + 1, len(idxs)):
                    i, j = idxs[p], idxs[q]
                    if hamming(sigs[i], sigs[j]) > 12:
                        continue
                    compared += 1
                    if jaccard(shs[i], shs[j]) < gate:
                        continue
                    if similarity(texts[i], texts[j]) < threshold:
                        continue
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri
        groups: dict[int, list[int]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        return [sorted(loaded[i][0].rel_path for i in idxs)
                for idxs in groups.values() if len(idxs) > 1]

    # -- the audit --------------------------------------------------------------------------------
    def audit(self, inactive_days: int = DEFAULT_INACTIVE_DAYS,
              near_dup_threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
              hot_min: int = 5, db_path: Path | str | None = None,
              max_runs: int = 0, use_cache: bool = True) -> MemoryAuditReport:
        t0 = time.perf_counter()
        fp = self.vault.fingerprint()
        # The vault fingerprint decides WHEN a report goes stale, but it cannot decide WHETHER two
        # reports are interchangeable: the same unchanged vault audited with --db and without it
        # answers different questions (hot/warm/cold need the database), and the thresholds are
        # caller arguments. So the parameters are part of the key.
        db = db_path if db_path is not None else self.db_path
        try:
            db_key = (str(Path(db).resolve()), Path(db).stat().st_mtime) if db else None
        except OSError:
            db_key = (str(db), 0.0)
        key = (str(self.vault.root), fp, db_key, int(inactive_days),
               round(float(near_dup_threshold), 4), int(hot_min), int(max_runs))
        if use_cache:
            hit = _CACHE.get(key)
            if hit is not None:
                return replace(hit, cached=True)
        report = self._audit_now(fp, t0, inactive_days, near_dup_threshold, hot_min, db_path, max_runs)
        if use_cache:
            _CACHE[key] = report
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.pop(next(iter(_CACHE)))
        return report

    def _audit_now(self, fp, t0, inactive_days, near_dup_threshold, hot_min, db_path, max_runs
                   ) -> MemoryAuditReport:
        loaded = self.load_notes()
        notes = [n for n, _, _ in loaded]
        by_path = {n.rel_path: n for n in notes}

        resolved, broken = self._link_graph(loaded)
        wikilinks_total = sum(len(v) for v in resolved.values())
        inbound: dict[str, int] = {n.rel_path: 0 for n in notes}
        for src, targets in resolved.items():
            for t in targets:
                if t in inbound:
                    inbound[t] += 1
        orphans = [n.rel_path for n in notes if inbound.get(n.rel_path, 0) == 0]

        by_hash: dict[str, list[str]] = {}
        for n in notes:
            by_hash.setdefault(n.content_hash, []).append(n.rel_path)
        dup_exact_groups = sorted([sorted(g) for g in by_hash.values() if len(g) > 1])
        dup_near_groups = self._near_dup_groups(loaded, near_dup_threshold)

        today = date.today()
        by_area: dict[str, int] = {}
        by_projeto: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        created_per_day: dict[str, int] = {}
        updated_per_day: dict[str, int] = {}
        missing_by_key: dict[str, int] = {}
        inactive: list[str] = []
        archived: list[str] = []
        superseded: list[str] = []
        bytes_total = tokens_total = provenance_tokens_total = 0
        for n in notes:
            bytes_total += n.bytes
            tokens_total += n.tokens_est
            provenance_tokens_total += estimate_tokens(render_provenance(NoteFacts(
                n.rel_path, title=n.title, area=n.area, type_=n.type_, status=n.status,
                projeto=n.projeto, created=n.created, updated=n.updated,
                superseded_by=n.superseded_by, has_frontmatter=n.has_frontmatter))
                + (" " + HISTORICAL_MARKER if n.is_historical else ""))
            by_area[n.area or "sem_area"] = by_area.get(n.area or "sem_area", 0) + 1
            key = n.project_slug or n.projeto or "sem_projeto"
            by_projeto[key] = by_projeto.get(key, 0) + 1
            if n.type_:
                by_type[n.type_] = by_type.get(n.type_, 0) + 1
            if n.status:
                by_status[n.status] = by_status.get(n.status, 0) + 1
            for k in n.missing_fields:
                missing_by_key[k] = missing_by_key.get(k, 0) + 1
            if n.created:
                created_per_day[n.created.isoformat()] = created_per_day.get(n.created.isoformat(), 0) + 1
            if n.updated:
                updated_per_day[n.updated.isoformat()] = updated_per_day.get(n.updated.isoformat(), 0) + 1
            if n.is_archived:
                archived.append(n.rel_path)
            if n.superseded_by:
                superseded.append(n.rel_path)
            if n.status == "ativo" and n.touched and (today - n.touched).days > inactive_days:
                inactive.append(n.rel_path)

        # -- consistency candidates: same title among active notes, or a note citing its successor
        conflicts: list[list[str]] = []
        by_title: dict[str, list[str]] = {}
        for n in notes:
            if n.status == "ativo" and n.title:
                by_title.setdefault(_norm(n.title), []).append(n.rel_path)
        conflicts_same_title = 0
        for group in by_title.values():
            if len(group) > 1:
                conflicts.append(sorted(group))
                conflicts_same_title += 1
        for n in notes:
            if not n.superseded_by:
                continue
            target = n.superseded_by.strip().rstrip(".md")
            peers = [p for p in notes
                     if Path(p.rel_path).stem.lower() == Path(target).stem.lower()
                     and p.rel_path != n.rel_path]
            group = sorted([n.rel_path] + [p.rel_path for p in peers])
            if group not in conflicts:
                conflicts.append(group)
        conflicts_superseded = sum(1 for n in notes if n.superseded_by)

        # -- boilerplate: sections whose normalized body repeats in more than one note
        section_notes: dict[str, set[str]] = {}
        section_tokens: dict[str, int] = {}
        heading_notes: dict[str, set[str]] = {}
        for note, _text, sections in loaded:
            note.sections = [s.heading_path for s in sections]
            for sec in sections:
                norm = _norm(sec.text)
                if not norm:
                    continue
                h = _sha256(norm)
                section_notes.setdefault(h, set()).add(note.rel_path)
                section_tokens[h] = section_tokens.get(h, 0) + estimate_tokens(sec.text)
                heading_notes.setdefault(_norm(sec.heading_path), set()).add(note.rel_path)
        repeated_keys = [h for h, paths in section_notes.items() if len(paths) > 1]
        notes_with_repeated: set[str] = set()
        for h in repeated_keys:
            notes_with_repeated |= section_notes[h]
        repeated_tokens = sum(section_tokens[h] for h in repeated_keys)
        repeated_headings = sorted(((h, len(p)) for h, p in heading_notes.items() if len(p) > 1),
                                   key=lambda kv: (-kv[1], kv[0]))

        # -- lifecycle: hot / warm / cold from delivered sources (benchmark.db, read-only)
        usage = MemoryUsage(db_path=None)
        db = db_path if db_path is not None else self.db_path
        if db is not None:
            try:
                counts, rows, deliveries = delivery_counts(db, max_runs=max_runs)
                usage = MemoryUsage(db_path=Path(db).name, runs_scanned=rows, deliveries=deliveries)
                hot, warm, cold = [], [], []
                for n in notes:
                    c = counts.get(n.rel_path, 0)
                    if c >= hot_min:
                        hot.append((n.rel_path, c))
                    elif c > 0:
                        warm.append((n.rel_path, c))
                    else:
                        cold.append((n.rel_path, 0))
                hot.sort(key=lambda kv: (-kv[1], kv[0]))
                warm.sort(key=lambda kv: (-kv[1], kv[0]))
                usage.hot, usage.warm, usage.cold = len(hot), len(warm), len(cold)
                usage.hot_top, usage.warm_top, usage.cold_top = hot[:25], warm[:25], cold[:25]
            except Exception as exc:  # noqa: BLE001 — a missing/locked db must not hide the audit
                usage.db_error = f"{type(exc).__name__}: {exc}"

        notes_count = len(notes)
        summary = MemoryAuditSummary(
            vault_notes=len(self.vault.list_markdown()), notes_scanned=notes_count,
            by_area=dict(sorted(by_area.items())), by_projeto=dict(sorted(by_projeto.items())),
            by_type=dict(sorted(by_type.items())), by_status=dict(sorted(by_status.items())),
            bytes_total=bytes_total, bytes_avg=round(bytes_total / notes_count, 1) if notes_count else 0.0,
            tokens_total=tokens_total, tokens_avg=round(tokens_total / notes_count, 1) if notes_count else 0.0,
            provenance_tokens_total=provenance_tokens_total,
            provenance_tokens_mean=round(provenance_tokens_total / notes_count, 1) if notes_count else 0.0,
            created_per_day=dict(sorted(created_per_day.items())),
            updated_per_day=dict(sorted(updated_per_day.items())),
            dup_exact=sum(len(g) - 1 for g in dup_exact_groups),
            dup_exact_groups=len(dup_exact_groups), dup_near_groups=len(dup_near_groups),
            orphan_count=len(orphans), wikilinks_total=wikilinks_total,
            wikilinks_broken_count=sum(len(v) for v in broken.values()),
            notes_without_fm=sum(1 for n in notes if not n.has_frontmatter),
            notes_missing_fields=sum(1 for n in notes if n.missing_fields),
            missing_fields_by_key=dict(sorted(missing_by_key.items())),
            inactive_days=inactive_days, inactive_gt_n=len(inactive),
            archived_count=len(archived), superseded_count=len(superseded),
            historical_count=len({*archived, *superseded}),
            conflicts=len(conflicts), conflicts_same_title=conflicts_same_title,
            conflicts_superseded=conflicts_superseded,
            hot_count=usage.hot, warm_count=usage.warm, cold_count=usage.cold,
            repeated_sections=len(repeated_keys),
            notes_with_repeated_sections=len(notes_with_repeated),
            repeated_section_tokens=repeated_tokens,
            repeated_section_token_share=(round(repeated_tokens / tokens_total, 4)
                                          if tokens_total else 0.0),
            db_runs_scanned=usage.runs_scanned, db_deliveries=usage.deliveries,
            memory_conflicts_detected=len(conflicts), memory_historical_demoted=len({*archived, *superseded}),
        )
        return MemoryAuditReport(
            vault=str(self.vault.root), vault_fingerprint=fp,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            scan_ms=round((time.perf_counter() - t0) * 1000, 1), cached=False, summary=summary,
            dup_exact=dup_exact_groups, dup_near=dup_near_groups, orphans=orphans,
            wikilinks_broken=broken,
            notes_without_frontmatter=[n.rel_path for n in notes if not n.has_frontmatter],
            notes_missing_fields={n.rel_path: n.missing_fields for n in notes if n.missing_fields},
            inactive=inactive, archived=archived, superseded=superseded, conflicts=conflicts,
            repeated_headings=repeated_headings[:25], usage=usage,
            parameters={"inactive_days": inactive_days, "near_dup_threshold": near_dup_threshold,
                        "hot_min": hot_min, "required_fields": list(REQUIRED_FIELDS)},
        )


#: Process-level cache: fingerprint -> report. A fingerprint change (count, total bytes, newest
#: mtime, path hash) invalidates it, so an edit to any note is picked up on the next audit.
_CACHE: dict[tuple[str, tuple], MemoryAuditReport] = {}
_CACHE_MAX = 8


def clear_cache() -> None:
    _CACHE.clear()