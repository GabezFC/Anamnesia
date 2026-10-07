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
from datetime import datetime, timezone
from pathlib import Path

from config import env_int
from config.paths import saved_context_dir

DEFAULT_MAX_BYTES = 64 * 1024
DEFAULT_RATE_PER_MIN = 30
ID_RE = re.compile(r"^[0-9a-f]{10}$")
_TMP_PREFIX = ".tmp-"
_NAME_RE = re.compile(r"^[a-z0-9-]+-([0-9a-f]{10})\.md$")


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
    ("credential assignment", re.compile(
        r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|MG_LOCAL_TOKEN)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{20,}")),
)


def scan_secrets(*texts: str) -> list[str]:
    """Labels of the secret patterns found in `texts` (empty list = clean)."""
    found: list[str] = []
    for label, rx in SECRET_PATTERNS:
        if any(rx.search(t or "") for t in texts) and label not in found:
            found.append(label)
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

    def to_dict(self, with_content: bool = True) -> dict:
        d = asdict(self)
        if not with_content:
            d.pop("content")
        return d


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _q(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(note: SavedNote) -> str:
    fm = ["---", f"id: {note.id}", f"title: {_q(note.title)}", f"type: contexto-salvo",
          f"project: {_q(note.project)}" if note.project else "project: null",
          f"tags: {_q(note.tags)}",
          f"source_agent: {_q(note.source_agent)}" if note.source_agent else "source_agent: null",
          f"created: {_q(note.created)}", f"updated: {_q(note.updated)}", "---", ""]
    return "\n".join(fm) + f"# {note.title}\n\n{note.content.strip()}\n"


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
        updated=meta.get("updated") or "", file=file)


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
        self._lock = threading.Lock()
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
    def save(self, title: str, content: str, tags: list[str] | None = None, project: str | None = None,
             source_agent: str | None = None) -> str:
        """Validate, then write one note atomically. Returns the note id."""
        title = (title or "").strip()
        content = content or ""
        tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        project = (project or "").strip() or None
        source_agent = (source_agent or "").strip() or None
        if not title or not content.strip():
            raise InvalidNote("título e conteúdo são obrigatórios")
        if len(title) > 200 or any(len(t) > 60 for t in tags) or len(tags) > 20:
            raise InvalidNote("título (<=200), tags (<=20, <=60 caracteres cada) fora do limite")
        if "\n" in title or "\r" in title:
            raise InvalidNote("o título deve ter uma linha")
        size = len(content.encode("utf-8"))
        if size > self.max_bytes:
            raise TooLarge(f"conteúdo com {size} bytes excede o limite de {self.max_bytes} bytes")
        found = scan_secrets(title, content, project or "", source_agent or "", *tags)
        if found:
            raise SecretDetected("conteúdo rejeitado: parece conter segredo (" + ", ".join(found)
                                 + "). Nada foi gravado; remova o segredo e tente de novo.")
        with self._lock:
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
            note = SavedNote(note_id, title, content, project, tags, source_agent, now, now, dest.name)
            self._write_atomic(dest, render(note))
        return note_id

    def get(self, note_id: str) -> SavedNote:
        p = self._path_for(note_id)
        if p is None:
            raise NoteNotFound("nota não encontrada")
        return parse(p.read_text(encoding="utf-8"), p.name)

    def list(self, project: str | None = None, tag: str | None = None) -> list[SavedNote]:
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
            out.append(n)
        out.sort(key=lambda n: (n.created, n.id), reverse=True)
        return out

    def delete(self, note_id: str) -> None:
        with self._lock:
            p = self._path_for(note_id)
            if p is None:
                raise NoteNotFound("nota não encontrada")
            p.unlink()

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
