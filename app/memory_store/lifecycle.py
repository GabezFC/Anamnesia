"""Memory lifecycle on top of the saved-context store (Onda 3: ANA-148, 150, 156, 157, 158, 160, 162, 163).

Everything here is deterministic, local, zero-token and works ONLY on the Gateway-owned saved-context
folder (never the user's vault). The store keeps the single write path (`SavedContextStore._mutate`,
`_write_atomic`); this module composes it:

  * find_similar / save_checked   ANA-148  near-duplicate + same-subject detection on write
  * history / diff / rollback     ANA-150  versions live in `<state>/history/<id>/<ts_ns>.md`
  * trash / restore / reap        ANA-150/157  soft delete, TTL expiry, dry-run reaper
  * feedback / usefulness         ANA-158/160  per-note verdicts, author-tagged, reviewed before calibration
  * contradictions                ANA-162  same subject + different number/date -> candidates for HUMAN review
  * audit / consolidate           ANA-156  lifecycle counters, duplicate rate, supersede proposals
  * export_jsonl / import_jsonl   ANA-163  `anamnesia-memory/1` with checksum, round-trip exact
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import time
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.memory_store.store import (
    FEEDBACK_VERDICTS, SCHEMA_VERSION, InvalidNote, InvalidNoteId, NoteNotFound, SavedContextError,
    SavedContextStore, SavedNote, _NAME_RE, _now, content_digest, parse, render, schema_v2_enabled, slugify,
)
from app.services.near_dup import similarity
from config import env_bool, env_float, env_int

EXPORT_FORMAT = "anamnesia-memory/1"
SIMILAR_THRESHOLD = 0.85   # reported as `similar`
DUPLICATE_THRESHOLD = 0.92  # treated as a duplicate by dedupe=skip/update


# ---------------------------------------------------------------------------------------------
# ANA-148: duplicate / contradiction detection on write
# ---------------------------------------------------------------------------------------------
def _norm_title(title: str) -> str:
    return slugify(title)


_NUM_RE = re.compile(r"\d+(?:[.,:/-]\d+)*")


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", ".") for m in _NUM_RE.finditer(text or "")}


def find_similar(store: SavedContextStore, title: str, content: str, project: str | None = None, *,
                 exclude_id: str | None = None, threshold: float | None = None) -> list[dict]:
    """Saved notes that look like (title, content). Each hit: {id, title, similarity, reason, status}.

    reasons: `near_duplicate` (sequence similarity >= threshold), `same_title` (normalised titles equal,
    contents differ), `possible_contradiction` (same subject, different numbers/dates). Superseded and
    archived notes are ignored: they are history, not competitors.
    """
    thr = SIMILAR_THRESHOLD if threshold is None else threshold
    nt, hits = _norm_title(title), []
    for n in store.list():
        if n.id == exclude_id or (n.status or "active") not in ("active", "reinforced"):  # ANAM-013
            continue
        if project and n.project and n.project != project:
            continue
        sim = similarity(content, n.content)
        same_title = _norm_title(n.title) == nt
        reason = None
        if sim >= thr:
            reason = "near_duplicate"
        elif same_title and _numbers(content) != _numbers(n.content):
            reason = "possible_contradiction"
        elif same_title:
            reason = "same_title"
        if reason:
            hits.append({"id": n.id, "title": n.title, "similarity": round(sim, 4), "reason": reason,
                         "status": n.status or "active"})
    hits.sort(key=lambda h: -h["similarity"])
    return hits


def suggested_action(similar: list[dict]) -> str:
    if not similar:
        return "none"
    if any(h["reason"] in ("possible_contradiction",) for h in similar):
        return "supersede"
    return "suggest_update"


def save_checked(store: SavedContextStore, title: str, content: str, tags=None, project=None,
                 source_agent=None, trust=None, *, dedupe: str | None = None, **v2) -> dict:
    """`store.save` plus ANA-148. Returns {id, saved, similar, action, [duplicate_of]}.

    dedupe (default env MG_MEMORY_DEDUPE, else `warn`):
      off    -> no check (old behaviour), `similar` is []
      warn   -> always saves; reports similar notes and a suggested action (suggest_update|supersede)
      skip   -> a near-duplicate (>= 0.92) is NOT written; returns the existing id with saved=False
      update -> a near-duplicate is updated in place (versioned, ANA-150) instead of creating a new note
    An explicit `supersedes=<id>` always wins and is never second-guessed.
    """
    mode = (dedupe or os.environ.get("MG_MEMORY_DEDUPE", "warn")).strip().lower()
    if mode not in ("off", "warn", "skip", "update"):
        raise InvalidNote("dedupe inválido (off|warn|skip|update)")
    # ANAM-042: triagem Laya na escrita (MG_LAYA_WRITE_TRIAGE=off|warn|block; padrão off = comportamento antigo).
    # Sinal ADICIONAL ao injection_screen: só eleva severidade; `block` recusa a escrita e devolve o motivo.
    triage = None
    if os.environ.get("MG_LAYA_WRITE_TRIAGE", "off").strip().lower() not in ("", "off"):
        from app.services.laya_decider import triage_write
        triage = triage_write("\n".join((title or "", content or ""))).to_dict()
        if triage["action"] == "block":
            return {"id": None, "saved": False, "similar": [], "action": "blocked_by_triage", "triage": triage}
    similar = [] if mode == "off" else find_similar(store, (title or "").strip(), content or "", (project or "").strip() or None)
    if v2.get("supersedes"):
        nid = store.save(title, content, tags, project, source_agent, trust, **v2)
        return {"id": nid, "saved": True, "similar": similar, "action": "supersede"}
    dup = next((h for h in similar if h["reason"] == "near_duplicate" and h["similarity"] >= DUPLICATE_THRESHOLD), None)
    if dup and mode == "skip":
        return {"id": dup["id"], "saved": False, "similar": similar, "action": "suggest_update", "duplicate_of": dup["id"]}
    if dup and mode == "update":
        store.update(dup["id"], title=title, content=content, tags=tags)
        return {"id": dup["id"], "saved": False, "updated": True, "similar": similar, "action": "suggest_update",
                "duplicate_of": dup["id"]}
    nid = store.save(title, content, tags, project, source_agent, trust, **v2)
    res = {"id": nid, "saved": True, "similar": similar, "action": suggested_action(similar)}
    if triage is not None:
        res["triage"] = triage
    return res


def contradictions(store: SavedContextStore, min_similarity: float = 0.5) -> list[dict]:
    """ANA-162: CANDIDATES for human review (never a verdict). Pairs of active notes about the same
    subject (same normalised title, or same project + high text overlap) whose numbers/dates differ."""
    notes = [n for n in store.list() if (n.status or "active") in ("active", "reinforced")]  # ANAM-013
    out = []
    for i, a in enumerate(notes):
        for b in notes[i + 1:]:
            if a.project != b.project:
                continue
            same_subject = _norm_title(a.title) == _norm_title(b.title)
            sim = similarity(a.content, b.content)
            if not (same_subject or sim >= max(min_similarity, 0.6)):
                continue
            na, nb = _numbers(a.content), _numbers(b.content)
            if na == nb or not (na and nb):
                continue
            if sim >= 0.995:
                continue
            out.append({"a": a.id, "b": b.id, "title_a": a.title, "title_b": b.title, "similarity": round(sim, 4),
                        "only_a": sorted(na - nb)[:5], "only_b": sorted(nb - na)[:5],
                        "verdict": None, "needs_human_review": True})
    return out


# ---------------------------------------------------------------------------------------------
# ANA-150: versions, diff, rollback, trash
# ---------------------------------------------------------------------------------------------
def history(store: SavedContextStore, note_id: str) -> list[dict]:
    """Versions of a note, oldest first: [{version, sha256, bytes, title}] (version = snapshot id)."""
    store._path_for(note_id)  # validates the id format
    d = store._history_dir(note_id)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.md"), key=lambda q: int(q.stem)):
            raw = p.read_bytes()
            try:
                title = parse(raw.decode("utf-8"), p.name).title
            except Exception:  # noqa: BLE001
                title = ""
            out.append({"version": p.stem, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "title": title})
    return out


def _version_text(store: SavedContextStore, note_id: str, version: str) -> str:
    if version in ("current", "head"):
        p = store._path_for(note_id)
        if p is None:
            raise NoteNotFound("nota não encontrada")
        return p.read_bytes().decode("utf-8")
    if not re.fullmatch(r"\d{1,24}", str(version)):
        raise InvalidNote("versão inválida")
    p = store._history_dir(note_id) / f"{version}.md"
    if not p.is_file():
        raise NoteNotFound("versão não encontrada")
    return p.read_bytes().decode("utf-8")


def diff(store: SavedContextStore, note_id: str, a: str, b: str = "current") -> str:
    ta, tb = _version_text(store, note_id, a), _version_text(store, note_id, b)
    return "".join(difflib.unified_diff(ta.splitlines(True), tb.splitlines(True), f"{note_id}@{a}", f"{note_id}@{b}"))


def rollback(store: SavedContextStore, note_id: str, version: str) -> SavedNote:
    """Restore a previous version BYTE FOR BYTE. The state being replaced is snapshotted first, so a
    rollback can itself be rolled back."""
    text = _version_text(store, note_id, version)
    with store._lock:
        p = store._path_for(note_id)
        if p is None:
            raise NoteNotFound("nota não encontrada")
        store._snapshot(note_id, p)
        store._write_atomic(p, text)
        return parse(text, p.name)


def trash_list(store: SavedContextStore) -> list[dict]:
    d = store.state_dir / "trash"
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*__*.md")):
            ts, _, name = p.name.partition("__")
            m = _NAME_RE.match(name)
            if not (ts.isdigit() and m):
                continue
            out.append({"trash_id": p.name, "id": m.group(1), "deleted_at": int(ts) // 10**9, "file": name})
    return out


def restore(store: SavedContextStore, trash_id: str) -> str:
    d = (store.state_dir / "trash").resolve()
    p = (d / trash_id).resolve()
    if p.parent != d or not p.is_file():
        raise NoteNotFound("item da lixeira não encontrado")
    _, _, name = p.name.partition("__")
    m = _NAME_RE.match(name)
    if not m:
        raise InvalidNoteId("item da lixeira inválido")
    with store._lock:
        if store._path_for(m.group(1)) is not None:
            raise SavedContextError("já existe uma nota com esse id")
        store.root.mkdir(parents=True, exist_ok=True)
        os.replace(p, store.root / name)
    return m.group(1)


def reap(store: SavedContextStore, *, dry_run: bool = True, now: datetime | None = None) -> dict:
    """ANA-157: move EXPIRED notes to the trash and purge trash items older than MG_MEMORY_TRASH_DAYS (30).
    `dry_run=True` (default) only reports. Nothing is ever hard-deleted without passing through the trash."""
    now = now or datetime.now(timezone.utc)
    expired = [n for n in store.list() if n.is_expired(now)]
    ttl_days = env_float("MG_MEMORY_TRASH_DAYS", 30.0)
    cutoff_ns = int((now - timedelta(days=ttl_days)).timestamp() * 1e9)
    purge = [t for t in trash_list(store) if t["deleted_at"] * 10**9 < cutoff_ns]
    rep = {"dry_run": dry_run, "expired": [{"id": n.id, "title": n.title, "expires_at": n.expires_at} for n in expired],
           "to_purge": [t["trash_id"] for t in purge], "moved": 0, "purged": 0}
    if dry_run:
        return rep
    for n in expired:
        with store._lock:
            p = store._path_for(n.id)
            if p is not None:
                store._snapshot(n.id, p)
                store.to_trash(p)
                rep["moved"] += 1
    for t in purge:
        try:
            (store.state_dir / "trash" / t["trash_id"]).unlink()
            rep["purged"] += 1
        except OSError:
            pass
    return rep


# ---------------------------------------------------------------------------------------------
# ANA-158 / ANA-160: feedback with authorship and review before calibration
# ---------------------------------------------------------------------------------------------
_FB_CONF_DELTA = {"useful": 0.05, "wrong": -0.2, "stale": -0.05}


def _fb_log(store: SavedContextStore) -> Path:
    return store.state_dir / "feedback.jsonl"


def feedback(store: SavedContextStore, note_id: str, verdict: str, reason: str | None = None, *,
             author: str | None = None, source: str = "user") -> dict:
    """Record a verdict on a note. Counters go into the note's frontmatter; the full event (with author and
    `reviewed: false`) goes into `<state>/feedback.jsonl`. `confidence` moves ONLY if the note already
    declares one (it is never invented: ANA-243). `source`: user | agent | auto (grounding_failed)."""
    verdict = (verdict or "").strip().lower()
    if verdict not in FEEDBACK_VERDICTS:
        raise InvalidNote(f"verdict inválido (use {', '.join(FEEDBACK_VERDICTS)})")
    reason = (reason or "").strip()
    if len(reason) > 500 or "\n" in reason:
        raise InvalidNote("reason deve ter uma linha e até 500 caracteres")
    author = (author or "").strip()[:80] or "anonymous"
    from app.memory_store.store import scan_secrets
    if scan_secrets(reason, author):
        raise InvalidNote("reason parece conter segredo; nada foi gravado")
    with store._lock:
        cur = store.get(note_id)
        ch: dict = {f"feedback_{verdict}": getattr(cur, f"feedback_{verdict}") + 1}
        if cur.schema < 2 and schema_v2_enabled():
            ch.update(schema=SCHEMA_VERSION, kind=cur.kind or "episodic", status=cur.status or "active",
                      source=cur.source or (f"agent:{cur.source_agent}" if cur.source_agent else "manual"))
        if cur.confidence is not None:
            ch["confidence"] = round(min(1.0, max(0.0, cur.confidence + _FB_CONF_DELTA[verdict])), 4)
        # `updated` is NOT bumped: a verdict is not an edit of the claim
        note = store._mutate(note_id, updated=cur.updated, **ch)
        ev = {"ts": time.time(), "note_id": note_id, "verdict": verdict, "reason": reason, "author": author,
              "source": source, "reviewed": False}
        _fb_log(store).parent.mkdir(parents=True, exist_ok=True)
        with open(_fb_log(store), "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return {"id": note_id, "verdict": verdict, "feedback_useful": note.feedback_useful,
            "feedback_wrong": note.feedback_wrong, "feedback_stale": note.feedback_stale,
            "confidence": note.confidence, "excluded_from_default_search": note.feedback_wrong >= 2}


def feedback_events(store: SavedContextStore, *, only_reviewed: bool | None = None) -> list[dict]:
    p = _fb_log(store)
    out = []
    if p.is_file():
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines()):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            ev["event_id"] = i
            if only_reviewed is None or bool(ev.get("reviewed")) == only_reviewed:
                out.append(ev)
    return out


def review_feedback(store: SavedContextStore, event_id: int, reviewer: str) -> dict:
    """ANA-160: a human marks an event reviewed. Only reviewed events may enter calibration."""
    p = _fb_log(store)
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    if not 0 <= event_id < len(lines):
        raise NoteNotFound("evento não encontrado")
    ev = json.loads(lines[event_id])
    ev.update(reviewed=True, reviewed_by=(reviewer or "").strip()[:80] or "unknown", reviewed_at=time.time())
    lines[event_id] = json.dumps(ev, ensure_ascii=False)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, p)
    return ev


def calibration_events(store: SavedContextStore) -> list[dict]:
    """Feedback allowed into calibration: has an author other than `anonymous` AND was reviewed by a human."""
    return [e for e in feedback_events(store, only_reviewed=True) if e.get("author") not in (None, "", "anonymous")]


def record_grounding_failure(store: SavedContextStore, sources: list[dict], *, run_id: str | None = None) -> int:
    """ANA-158: `grounding_failed` is an automatic `stale` signal for the SAVED notes among the sources.
    Weak by design (source=auto, never reviewed): it flags for audit, it does not exclude anything alone."""
    n = 0
    for s in sources or []:
        f = (s.get("file") if isinstance(s, dict) else str(s)) or ""
        m = _NAME_RE.match(f.rsplit("/", 1)[-1])
        if f.startswith("saved_context/") and m:
            try:
                feedback(store, m.group(1), "stale", f"grounding_failed run={run_id or '?'}", author="system:grounding",
                         source="auto")
                n += 1
            except SavedContextError:
                pass
    return n


def usefulness(store: SavedContextStore) -> list[dict]:
    """Per-note utility report: useful / wrong / stale counters and a net score, best first."""
    rows = [{"id": n.id, "title": n.title, "useful": n.feedback_useful, "wrong": n.feedback_wrong,
             "stale": n.feedback_stale, "net": n.feedback_useful - n.feedback_wrong - n.feedback_stale}
            for n in store.list() if n.feedback_useful or n.feedback_wrong or n.feedback_stale]
    rows.sort(key=lambda r: (-r["net"], r["id"]))
    return rows


# ---------------------------------------------------------------------------------------------
# ANA-156: lifecycle audit, consolidation, v1 -> v2 migration
# ---------------------------------------------------------------------------------------------
def audit(store: SavedContextStore) -> dict:
    notes = store.list()
    kinds: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for n in notes:
        kinds[n.kind or "(v1)"] = kinds.get(n.kind or "(v1)", 0) + 1
        statuses[n.status or "(v1)"] = statuses.get(n.status or "(v1)", 0) + 1
    active = [n for n in notes if (n.status or "active") == "active"]
    dups = 0
    for i, a in enumerate(active):
        if any(similarity(a.content, b.content) >= DUPLICATE_THRESHOLD for b in active[:i]):
            dups += 1
    bad = [n.id for n in notes if n.integrity_ok() is False]
    return {"total": len(notes), "active": len(active), "by_kind": kinds, "by_status": statuses,
            "schema_v1": sum(1 for n in notes if n.schema < 2), "schema_v2": sum(1 for n in notes if n.schema >= 2),
            "expired": sum(1 for n in notes if n.is_expired()),
            "stale_flagged": sum(1 for n in notes if n.feedback_stale), "wrong_flagged": sum(1 for n in notes if n.feedback_wrong),
            "duplicates": dups, "duplicate_rate": round(dups / len(active), 4) if active else 0.0,
            "integrity_failures": bad, "trash": len(trash_list(store))}


def consolidate(store: SavedContextStore, *, apply: bool = False) -> dict:
    """Group near-duplicates among ACTIVE notes. For each group the newest note is kept and the others are
    proposed (apply=True: marked) `superseded` by it. Nothing is deleted; every change is versioned."""
    active = sorted((n for n in store.list() if (n.status or "active") == "active"), key=lambda n: (n.created, n.id))
    groups: list[list[SavedNote]] = []
    for n in active:
        for g in groups:
            if similarity(n.content, g[0].content) >= DUPLICATE_THRESHOLD:
                g.append(n)
                break
        else:
            groups.append([n])
    plan = [{"keep": g[-1].id, "supersede": [x.id for x in g[:-1]]} for g in groups if len(g) > 1]
    done = 0
    if apply:
        for item in plan:
            for old in item["supersede"]:
                store._mutate(old, schema=SCHEMA_VERSION, status="superseded", superseded_by=item["keep"],
                              kind=store.get(old).kind or "episodic",
                              source=store.get(old).source or "manual", updated=store.get(old).updated)
                done += 1
    return {"apply": apply, "groups": plan, "superseded": done}


def migrate_v1(store: SavedContextStore, *, dry_run: bool = True) -> dict:
    """Upgrade v1 notes to schema 2 in place (additive). A JSONL export is written FIRST (rollback path)."""
    v1 = [n for n in store.list() if n.schema < 2]
    rep = {"dry_run": dry_run, "candidates": [n.id for n in v1], "migrated": 0, "backup": None}
    if dry_run or not v1:
        return rep
    bdir = store.state_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    bk = bdir / f"pre-migrate-{time.time_ns()}.jsonl"
    bk.write_text(export_jsonl(store), encoding="utf-8", newline="\n")
    rep["backup"] = str(bk)
    for n in v1:
        store._mutate(n.id, schema=SCHEMA_VERSION, kind=n.kind or "episodic", status=n.status or "active",
                      source=n.source or (f"agent:{n.source_agent}" if n.source_agent else "manual"),
                      content_sha256=content_digest(n.content), updated=n.updated)
        rep["migrated"] += 1
    return rep


# ---------------------------------------------------------------------------------------------
# ANA-163: portable JSONL with checksum
# ---------------------------------------------------------------------------------------------
_FIELDS = [f.name for f in fields(SavedNote)]


def export_jsonl(store: SavedContextStore) -> str:
    """Line 1: header {format, count, sha256-of-the-record-lines}. Lines 2..: one note each, ALL fields."""
    recs = [json.dumps({k: getattr(n, k) for k in _FIELDS}, ensure_ascii=False, sort_keys=True)
            for n in sorted(store.list(), key=lambda n: (n.created, n.id))]
    body = "\n".join(recs)
    head = {"format": EXPORT_FORMAT, "count": len(recs), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}
    return json.dumps(head) + "\n" + body + ("\n" if recs else "")


def import_jsonl(store: SavedContextStore, text: str, *, overwrite: bool = False) -> dict:
    """Verify format + count + checksum + every note's own content hash BEFORE writing anything."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise InvalidNote("arquivo vazio")
    try:
        head = json.loads(lines[0])
    except ValueError:
        raise InvalidNote("cabeçalho inválido") from None
    if head.get("format") != EXPORT_FORMAT:
        raise InvalidNote(f"formato desconhecido (esperado {EXPORT_FORMAT})")
    recs = lines[1:]
    if head.get("count") != len(recs):
        raise InvalidNote("contagem de registros não confere")
    if hashlib.sha256("\n".join(recs).encode("utf-8")).hexdigest() != head.get("sha256"):
        raise InvalidNote("checksum não confere: arquivo corrompido ou alterado")
    notes = []
    for r in recs:
        d = json.loads(r)
        unknown = set(d) - set(_FIELDS)
        if unknown:
            raise InvalidNote(f"campos desconhecidos: {sorted(unknown)}")
        n = SavedNote(**{k: d[k] for k in d})
        if not re.fullmatch(r"[0-9a-f]{10}", n.id or ""):
            raise InvalidNoteId("id inválido no arquivo")
        if not _NAME_RE.match(n.file or ""):
            raise InvalidNote("nome de arquivo inválido no arquivo")
        if n.integrity_ok() is False:
            raise InvalidNote(f"nota {n.id}: content_sha256 não confere")
        notes.append(n)
    imported = skipped = 0
    with store._lock:
        for n in notes:
            existing = store._path_for(n.id)
            if existing is not None and not overwrite:
                skipped += 1
                continue
            if existing is not None:
                store._snapshot(n.id, existing)
                if existing.name != n.file:
                    existing.unlink()
            store._write_atomic(store.root / n.file, render(n))
            imported += 1
    return {"imported": imported, "skipped": skipped, "count": len(notes)}
