"""Gateway-owned store for agent-saved context (Fase 7, decision "contexto salvo em Markdown").

One Markdown file per note under `<user_data_dir>/saved_context/`, separate from the user's vault
(which stays READ ONLY). Properties:

  * atomic writes: temp file (hidden, same folder) + fsync + os.replace -- a crash leaves either
    the old state or the complete new file, never a partial note;
  * unique files: `<ascii-kebab-slug>-<10 hex id>.md`; the id (not the slug) is the handle;
  * guard rails: size cap, per-minute rate cap, and a secret scanner that REJECTS (never stores)
    API-key-like material;
  * export (zip) and forget_all(confirm=True).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import tempfile
import threading
import time
import unicodedata
import zipfile
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import env_bool, env_int
from config.paths import saved_context_dir

DEFAULT_MAX_BYTES = 64 * 1024
DEFAULT_RATE_PER_MIN = 30
ID_RE = re.compile(r"^[0-9a-f]{10}$")
_TMP_PREFIX = ".tmp-"
_NAME_RE = re.compile(r"^[a-z0-9-]+-([0-9a-f]{10})\.md$")

# ANA-145: schema v2 vocabulary
KINDS = ("decision", "fact", "preference", "task", "episodic")
DEFAULT_KIND = "episodic"      # least assertive kind when the caller does not say
NOTE_STATUSES = ("active", "superseded", "archived")
SCHEMA_VERSION = 2
FEEDBACK_VERDICTS = ("useful", "wrong", "stale")


def schema_v2_enabled() -> bool:
    """MG_MEMORY_SCHEMA_V2=0 is the rollback: new notes are written exactly as before (v1)."""
    return env_bool("MG_MEMORY_SCHEMA_V2", True)


def content_digest(content: str) -> str:
    return hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()


class SavedContextError(Exception):
    """Base class; `.status` is the HTTP status the API maps it to."""
    status = 400


class SecretDetected(SavedContextError):
    status = 422


class TooLarge(SavedContextError):
    status = 413


class RateLimited(SavedContextError):
    status = 429


class NoteNotFound(SavedContextError):
    status = 404


class InvalidNoteId(SavedContextError):
    status = 400


class InvalidNote(SavedContextError):
    status = 422


class ConfirmationRequired(SavedContextError):
    status = 400


class IntegrityError(SavedContextError):
    status = 422


# (label, pattern). Labels are reported; the matched text never is.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----")),
    ("API key (sk-...)", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]{16,}", re.I)),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    # ANA-050 / P-07
    ("Azure storage key / connection string", re.compile(
        r"(?i)(?:AccountKey|SharedAccessKey|SharedAccessSignature)\s*=\s*[A-Za-z0-9+/=%]{20,}")),
    ("Azure SAS token", re.compile(r"(?i)[?&]sig=[A-Za-z0-9%+/=]{30,}")),
    ("GCP service-account JSON", re.compile(r'"type"\s*:\s*"service_account"|"private_key_id"\s*:\s*"[0-9a-f]{20,}"')),
    (".npmrc auth token", re.compile(r"(?i)(?://[^\s/]+/)?:?_authToken\s*=\s*\S{10,}")),
    ("DB connection string with password", re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)://[^\s:@/]+:[^\s@/]{3,}@")),
    ("Stripe/Twilio/SendGrid key", re.compile(r"\b(?:sk_live|rk_live|pk_live)_[A-Za-z0-9]{16,}|\bSG\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}")),
    ("credential assignment", re.compile(
        r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|MG_LOCAL_TOKEN)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{20,}")),
)


_INVISIBLE = re.compile("[" + "".join(chr(c) for c in (0x200b, 0x200c, 0x200d, 0x200e, 0x200f, 0x202a, 0x202b, 0x202c, 0x202d, 0x202e, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0xfeff, 0x00ad)) + "]")
_TOKENISH = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")


def _shannon(s: str) -> float:
    from math import log2
    from collections import Counter
    n = len(s)
    return -sum(c / n * log2(c / n) for c in Counter(s).values())


def _high_entropy(text: str) -> bool:
    """A long, mixed-class, high-entropy token (>= 4.2 bits/char) that is not a hash/uuid-looking hex id."""
    for m in _TOKENISH.finditer(text):
        tok = m.group(0)
        if re.fullmatch(r"[0-9a-fA-F\-]+", tok):  # git sha / uuid / content hash: not a secret
            continue
        if sum(c.isdigit() for c in tok) < 3 or not any(c.isalpha() for c in tok):
            continue
        if _shannon(tok) >= 4.2:
            return True
    return False


def scan_secrets(*texts: str) -> list[str]:
    """Labels of the secret patterns found in `texts` (empty list = clean).

    ANA-050: text is NFKC-normalised and stripped of zero-width characters before matching, so
    fullwidth / split-by-invisible-char obfuscation does not evade the regexes."""
    import unicodedata
    norm = [_INVISIBLE.sub("", unicodedata.normalize("NFKC", t or "")) for t in texts]
    found: list[str] = []
    for label, rx in SECRET_PATTERNS:
        if any(rx.search(t) for t in norm) and label not in found:
            found.append(label)
    if not found and any(_high_entropy(t) for t in norm):
        found.append("high-entropy token")
    return found


def slugify(text: str, max_len: int = 60) -> str:
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", norm.lower()).strip("-")[:max_len].strip("-")
    return slug or "nota"


@dataclass
class SavedNote:
    id: str
    title: str
    content: str
    project: str | None = None
    tags: list[str] = field(default_factory=list)
    source_agent: str | None = None
    created: str = ""
    updated: str = ""
    file: str = ""
    trust: str | None = None  # ANA-029: "untrusted" for agent-written notes (data, never instructions)
    # -- ANA-145 schema v2 (all optional: a v1 file parses with these at their defaults) ------------
    schema: int = 1
    kind: str | None = None            # decision | fact | preference | task | episodic
    status: str | None = None          # active | superseded | archived
    expires_at: str | None = None      # ISO-8601; honoured by list/search (ANA-157)
    confidence: float | None = None    # 0..1, ONLY when the caller declares it (never computed: ANA-243)
    source: str | None = None          # run_id / url / agent:<name> -- where the claim came from
    supersedes: str | None = None      # id of the note this one replaces (ANA-148)
    superseded_by: str | None = None   # id of the note that replaced this one
    content_sha256: str | None = None
    feedback_useful: int = 0           # ANA-158 counters
    feedback_wrong: int = 0
    feedback_stale: int = 0

    def is_expired(self, now: datetime | None = None) -> bool:
        exp = _parse_dt(self.expires_at)
        if exp is None:
            return False
        return exp <= (now or datetime.now(timezone.utc))

    def integrity_ok(self) -> bool | None:
        """True/False when the note carries a content hash, None for a v1 note (nothing to check)."""
        if not self.content_sha256:
            return None
        return content_digest(self.content) == self.content_sha256

    def to_dict(self, with_content: bool = True) -> dict:
        d = asdict(self)
        d["expired"] = self.is_expired()
        if not with_content:
            d.pop("content")
        return d


def _parse_dt(value) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            dt = datetime.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # naive == local time
    return dt.astimezone(timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _q(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(note: SavedNote) -> str:
    fm = ["---", f"id: {note.id}", f"title: {_q(note.title)}", f"type: contexto-salvo",
          f"project: {_q(note.project)}" if note.project else "project: null",
          f"tags: {_q(note.tags)}",
          f"source_agent: {_q(note.source_agent)}" if note.source_agent else "source_agent: null",
          f"created: {_q(note.created)}", f"updated: {_q(note.updated)}",
          # ANA-029: `projeto:` makes scope filters (projeto:<slug>) see the note ONLY in its own project
          *([f"projeto: {_q(note.project)}"] if note.project else []),
          *([f"trust: {_q(note.trust)}"] if note.trust else []), *_render_v2(note), "---", ""]
    return "\n".join(fm) + f"# {note.title}\n\n{note.content.strip()}\n"


def _render_v2(note: SavedNote) -> list[str]:
    """ANA-145: extra frontmatter lines. Empty for a v1 note, so a v1 file re-renders byte-identically."""
    if note.schema < 2:
        return []
    out = [f"schema: {note.schema}", f"kind: {_q(note.kind or DEFAULT_KIND)}",
           f"status: {_q(note.status or 'active')}"]
    if note.expires_at:
        out.append(f"expires_at: {_q(note.expires_at)}")
    if note.confidence is not None:
        out.append(f"confidence: {float(note.confidence):g}")
    if note.source:
        out.append(f"source: {_q(note.source)}")
    if note.supersedes:
        out.append(f"supersedes: {_q(note.supersedes)}")
    if note.superseded_by:
        out.append(f"superseded_by: {_q(note.superseded_by)}")
    if note.content_sha256:
        out.append(f"content_sha256: {_q(note.content_sha256)}")
    for k in ("feedback_useful", "feedback_wrong", "feedback_stale"):
        if getattr(note, k):
            out.append(f"{k}: {int(getattr(note, k))}")
    return out


def _scalar(raw: str):
    raw = raw.strip()
    if raw[:1] in ('"', "["):
        try:
            return json.loads(raw)
        except ValueError:
            return raw.strip('"')
    return None if raw in ("", "null") else raw


def parse(text: str, file: str = "") -> SavedNote:
    m = re.match(r"\A---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    if not m:
        raise InvalidNote(f"frontmatter ausente em {file or 'nota'}")
    meta = {}
    for line in m.group(1).split("\n"):
        k, sep, v = line.partition(":")
        if sep:
            meta[k.strip()] = _scalar(v)
    body = text.replace("\r\n", "\n")[m.end():]
    title = meta.get("title") or ""
    head = f"# {title}\n\n"
    body = body[len(head):] if body.startswith(head) else body
    return SavedNote(
        id=str(meta.get("id") or ""), title=title, content=body.rstrip("\n"),
        project=meta.get("project"), tags=list(meta.get("tags") or []),
        source_agent=meta.get("source_agent"), created=meta.get("created") or "",
        updated=meta.get("updated") or "", file=file, trust=meta.get("trust"),
        schema=_int(meta.get("schema"), 1), kind=meta.get("kind"), status=meta.get("status"),
        expires_at=meta.get("expires_at"), confidence=_float(meta.get("confidence")),
        source=meta.get("source"), supersedes=meta.get("supersedes"),
        superseded_by=meta.get("superseded_by"), content_sha256=meta.get("content_sha256"),
        feedback_useful=_int(meta.get("feedback_useful"), 0), feedback_wrong=_int(meta.get("feedback_wrong"), 0),
        feedback_stale=_int(meta.get("feedback_stale"), 0))


def _int(v, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _float(v) -> float | None:
    try:
        return None if v in (None, "") else float(str(v).strip())
    except ValueError:
        return None


def _replace(src, dst) -> None:  # indirection so tests can simulate a crash between temp and replace
    os.replace(src, dst)


class SavedContextStore:
    def __init__(self, root: Path | str | None = None, *, max_bytes: int | None = None,
                 rate_per_min: int | None = None, clock=time.monotonic):
        self.root = Path(root) if root is not None else saved_context_dir()
        self.max_bytes = max_bytes if max_bytes is not None else env_int("MG_SAVED_MAX_BYTES", DEFAULT_MAX_BYTES)
        self.rate_per_min = (rate_per_min if rate_per_min is not None
                             else env_int("MG_SAVED_RATE_PER_MIN", DEFAULT_RATE_PER_MIN))
        self._clock = clock
        # ANA-150/157: history, trash, backups and the feedback log live NEXT TO the notes folder
        # (never inside it), so the folder the index mounts only ever contains live notes.
        self.state_dir = self.root.parent / (self.root.name + "_state")
        self._lock = threading.RLock()
        self._hits: deque[float] = deque()

    # -- helpers ---------------------------------------------------------------------------
    def _check_rate(self) -> None:
        now = self._clock()
        while self._hits and now - self._hits[0] >= 60:
            self._hits.popleft()
        if self.rate_per_min > 0 and len(self._hits) >= self.rate_per_min:
            raise RateLimited(f"limite de {self.rate_per_min} notas por minuto atingido; tente de novo em instantes")
        self._hits.append(now)

    def _path_for(self, note_id: str) -> Path | None:
        if not isinstance(note_id, str) or not ID_RE.match(note_id):
            raise InvalidNoteId("id de nota inválido")
        if not self.root.is_dir():
            return None
        for p in self.root.iterdir():
            m = _NAME_RE.match(p.name)
            if m and m.group(1) == note_id:
                return p
        return None

    def _write_atomic(self, dest: Path, text: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=_TMP_PREFIX, suffix=".part", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            _replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- API -------------------------------------------------------------------------------
    def _validate(self, title: str, content: str, tags: list[str], project: str | None,
                  source_agent: str | None, source: str | None = None) -> None:
        if not title or not content.strip():
            raise InvalidNote("título e conteúdo são obrigatórios")
        if len(project or "") > 80 or len(source_agent or "") > 80:  # ANA-050: bound the other free-text fields
            raise InvalidNote("project/source_agent acima de 80 caracteres")
        if len(source or "") > 300:
            raise InvalidNote("source acima de 300 caracteres")
        if len(title) > 200 or any(len(t) > 60 for t in tags) or len(tags) > 20:
            raise InvalidNote("título (<=200), tags (<=20, <=60 caracteres cada) fora do limite")
        if "\n" in title or "\r" in title or "\n" in (source or "") or "\r" in (source or ""):
            raise InvalidNote("título e source devem ter uma linha")
        size = len(content.encode("utf-8"))
        if size > self.max_bytes:
            raise TooLarge(f"conteúdo com {size} bytes excede o limite de {self.max_bytes} bytes")
        found = scan_secrets(title, content, project or "", source_agent or "", source or "", *tags)
        if found:
            raise SecretDetected("conteúdo rejeitado: parece conter segredo (" + ", ".join(found)
                                 + "). Nada foi gravado; remova o segredo e tente de novo.")

    @staticmethod
    def _v2_fields(kind, expires_at, ttl_days, confidence, source, source_agent) -> dict:
        """Validate/normalise the ANA-145 fields. Raises InvalidNote on a bad value."""
        kind = (kind or "").strip().lower() or None
        if kind is not None and kind not in KINDS:
            raise InvalidNote(f"kind inválido: {kind!r} (use um de {', '.join(KINDS)})")
        exp = None
        if expires_at:
            dt = _parse_dt(str(expires_at))
            if dt is None:
                raise InvalidNote("expires_at inválido (use ISO-8601, ex.: 2026-12-31 ou 2026-12-31T10:00:00)")
            exp = dt.astimezone().isoformat(timespec="seconds")
        elif ttl_days is not None:
            try:
                days = float(ttl_days)
            except (TypeError, ValueError):
                raise InvalidNote("ttl_days inválido") from None
            if not 0 < days <= 36500:
                raise InvalidNote("ttl_days deve estar entre 0 (exclusivo) e 36500")
            exp = (datetime.now(timezone.utc) + timedelta(days=days)).astimezone().isoformat(timespec="seconds")
        conf = None
        if confidence is not None:
            try:
                conf = float(confidence)
            except (TypeError, ValueError):
                raise InvalidNote("confidence inválida") from None
            if not 0.0 <= conf <= 1.0:
                raise InvalidNote("confidence deve estar entre 0 e 1")
        src = (source or "").strip() or (f"agent:{source_agent}" if source_agent else "manual")
        return {"kind": kind or DEFAULT_KIND, "expires_at": exp, "confidence": conf, "source": src}

    def save(self, title: str, content: str, tags: list[str] | None = None, project: str | None = None,
             source_agent: str | None = None, trust: str | None = None, *, kind: str | None = None,
             expires_at: str | None = None, ttl_days: float | None = None, confidence: float | None = None,
             source: str | None = None, supersedes: str | None = None) -> str:
        """Validate, then write one note atomically. Returns the note id.

        ANA-145: with MG_MEMORY_SCHEMA_V2 on (default) the note is written as schema 2 -- kind, status,
        source (never empty: run_id/url, else `agent:<name>`, else `manual`), content_sha256, optional
        expires_at/confidence. `supersedes=<id>` marks that note `status: superseded` (never deletes it).
        """
        title = (title or "").strip()
        content = content or ""
        tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        project = (project or "").strip() or None
        source_agent = (source_agent or "").strip() or None
        self._validate(title, content, tags, project, source_agent, source)
        v2 = schema_v2_enabled()
        extra = self._v2_fields(kind, expires_at, ttl_days, confidence, source, source_agent) if v2 else {}
        if not v2 and any(x is not None for x in (kind, expires_at, ttl_days, confidence, supersedes)):
            raise InvalidNote("campos do esquema v2 recusados: MG_MEMORY_SCHEMA_V2=0")
        with self._lock:
            old = None
            if supersedes:
                old = self.get(supersedes)  # NoteNotFound / InvalidNoteId propagate
            self._check_rate()
            slug = slugify(title)
            for _ in range(20):
                note_id = secrets.token_hex(5)
                dest = self.root / f"{slug}-{note_id}.md"
                if not dest.exists() and self._path_for(note_id) is None:
                    break
            else:  # pragma: no cover - 40 bits of entropy
                raise SavedContextError("não foi possível gerar um id único")
            now = _now()
            note = SavedNote(note_id, title, content, project, tags, source_agent, now, now, dest.name, trust)
            if v2:
                note.schema = SCHEMA_VERSION
                note.status = "active"
                note.content_sha256 = content_digest(content)
                note.supersedes = supersedes or None
                for k, val in extra.items():
                    setattr(note, k, val)
            self._write_atomic(dest, render(note))
            if old is not None and old.id != note_id:
                self._mutate(old.id, status="superseded", superseded_by=note_id)
        return note_id

    def get(self, note_id: str) -> SavedNote:
        p = self._path_for(note_id)
        if p is None:
            raise NoteNotFound("nota não encontrada")
        return parse(p.read_text(encoding="utf-8"), p.name)

    # -- ANA-150: versioned update --------------------------------------------------------
    def _history_dir(self, note_id: str) -> Path:
        return self.state_dir / "history" / note_id

    def _snapshot(self, note_id: str, path: Path) -> Path:
        """Copy the CURRENT bytes of a note into history before it changes. Returns the snapshot."""
        d = self._history_dir(note_id)
        d.mkdir(parents=True, exist_ok=True)
        snap = d / f"{time.time_ns()}.md"
        snap.write_bytes(path.read_bytes())
        return snap

    def _mutate(self, note_id: str, **changes) -> SavedNote:
        """Rewrite one note with `changes` applied (history snapshot first, atomic write, `updated` bumped).

        Only fields of SavedNote may be changed; id/created/file never are. content_sha256 follows the
        content. Caller validates; this is the single write path for update/supersede/feedback/migrate.
        """
        with self._lock:
            p = self._path_for(note_id)
            if p is None:
                raise NoteNotFound("nota não encontrada")
            note = parse(p.read_text(encoding="utf-8"), p.name)
            self._snapshot(note_id, p)
            for k, v in changes.items():
                if k in ("id", "created", "file"):
                    continue
                setattr(note, k, v)
            if note.schema >= 2:
                note.content_sha256 = content_digest(note.content)
            if "updated" not in changes:
                note.updated = _now()
            self._write_atomic(p, render(note))
            return note

    def update(self, note_id: str, *, title: str | None = None, content: str | None = None,
               tags: list[str] | None = None, kind: str | None = None, status: str | None = None,
               expires_at: str | None = None, ttl_days: float | None = None,
               confidence: float | None = None, source: str | None = None) -> SavedNote:
        """Edit a note. The previous version is kept under `<state>/history/<id>/`. Upgrades a v1 note to v2."""
        cur = self.get(note_id)
        new_title = cur.title if title is None else title.strip()
        new_content = cur.content if content is None else content
        new_tags = cur.tags if tags is None else [str(t).strip() for t in tags if str(t).strip()]
        self._validate(new_title, new_content, new_tags, cur.project, cur.source_agent, source)
        ch: dict = {"title": new_title, "content": new_content.strip("\n") if content is not None else cur.content,
                    "tags": new_tags}
        if schema_v2_enabled() or cur.schema >= 2:
            f = self._v2_fields(kind or cur.kind, expires_at or cur.expires_at, None if expires_at else ttl_days,
                                confidence if confidence is not None else cur.confidence,
                                source or cur.source, cur.source_agent)
            ch.update(f, schema=SCHEMA_VERSION, status=cur.status or "active")
            if status is not None:
                if status not in NOTE_STATUSES:
                    raise InvalidNote(f"status inválido (use {', '.join(NOTE_STATUSES)})")
                ch["status"] = status
        with self._lock:
            self._check_rate()
            return self._mutate(note_id, **ch)

    def list(self, project: str | None = None, tag: str | None = None, *, kind: str | None = None,
             include_expired: bool = True) -> list[SavedNote]:
        out: list[SavedNote] = []
        if not self.root.is_dir():
            return out
        for p in sorted(self.root.iterdir()):
            if not _NAME_RE.match(p.name):
                continue
            try:
                n = parse(p.read_text(encoding="utf-8"), p.name)
            except (OSError, SavedContextError):
                continue
            if project and n.project != project:
                continue
            if tag and tag not in n.tags:
                continue
            if kind and n.kind != kind:
                continue
            if not include_expired and n.is_expired():
                continue
            out.append(n)
        # ANA-157: expired notes are demoted to the end of the listing (and flagged `expired` in to_dict)
        out.sort(key=lambda n: (n.created, n.id), reverse=True)
        out.sort(key=lambda n: n.is_expired())
        return out

    def delete(self, note_id: str) -> None:
        """ANA-150: soft delete -- the file moves to `<state>/trash/` (purged after MG_MEMORY_TRASH_DAYS by
        `reap`). MG_MEMORY_SOFT_DELETE=0 restores the old hard delete."""
        with self._lock:
            p = self._path_for(note_id)
            if p is None:
                raise NoteNotFound("nota não encontrada")
            if env_bool("MG_MEMORY_SOFT_DELETE", True):
                self.to_trash(p)
            else:
                p.unlink()

    def to_trash(self, p: Path) -> Path:
        d = self.state_dir / "trash"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{time.time_ns()}__{p.name}"
        os.replace(p, dest)
        return dest

    def export_zip(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            if self.root.is_dir():
                for p in sorted(self.root.iterdir()):
                    if _NAME_RE.match(p.name):
                        z.write(p, f"saved_context/{p.name}")
        return buf.getvalue()

    def forget_all(self, confirm: bool = False) -> int:
        """Delete every saved note (and stray temp files). Needs `confirm=True` literally."""
        if confirm is not True:
            raise ConfirmationRequired("forget_all exige confirm=True")
        n = 0
        with self._lock:
            if env_bool("MG_MEMORY_FORGET_BACKUP", True) and self.root.is_dir() \
                    and any(_NAME_RE.match(p.name) for p in self.root.iterdir()):
                # ANA-150: forget_all always leaves a restorable zip behind
                bdir = self.state_dir / "backups"
                bdir.mkdir(parents=True, exist_ok=True)
                (bdir / f"forget-{time.time_ns()}.zip").write_bytes(self.export_zip())
            if self.root.is_dir():
                for p in list(self.root.iterdir()):
                    if _NAME_RE.match(p.name):
                        p.unlink()
                        n += 1
                    elif p.name.startswith(_TMP_PREFIX):
                        p.unlink()
            self._hits.clear()
        return n


_stores: dict[str, SavedContextStore] = {}
_stores_lock = threading.Lock()


def get_store() -> SavedContextStore:
    """Process-wide store for the CURRENT data dir (keeps the rate window across calls)."""
    root = saved_context_dir()
    key = str(root)
    with _stores_lock:
        if key not in _stores:
            _stores[key] = SavedContextStore(root)
        return _stores[key]
