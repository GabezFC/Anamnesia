"""Project registry (SQLite) and path-safety helpers for the read-only file explorer (S5)."""
from __future__ import annotations

import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

LIST_CAP = 500
SEARCH_CAP = 200
SCAN_CAP = 50_000
CONTENT_RESULT_CAP = 200
CONTENT_MAX_FILE_BYTES = 1024 * 1024
CONTENT_MAX_TOTAL_BYTES = 64 * 1024 * 1024
CONTENT_MAX_SECONDS = 5.0
SNIPPET_CHARS = 160
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}


class ProjectError(ValueError):
    pass


class PathEscapeError(ProjectError):
    """A relative path tried to leave the project directory (`..`, absolute, symlink escape)."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: str
    created_at: float

    def to_dict(self) -> dict:
        return asdict(self)


def _is_within(root: Path, target: Path) -> bool:
    return target == root or root in target.parents


def safe_join(project_path: str | os.PathLike, rel: str | os.PathLike = "") -> Path:
    """Resolve `rel` under `project_path`; raise PathEscapeError if the REAL path leaves it.

    Rejects absolute paths, drive letters / NTFS stream syntax, NUL bytes, any `..` component, and
    symlinks/junctions whose target is outside the project (the final path is `resolve()`d).
    """
    root = Path(project_path).resolve()
    rel_s = os.fspath(rel) if rel is not None else ""
    if "\x00" in rel_s:
        raise PathEscapeError("caminho inválido")
    if rel_s in ("", ".", "/", "\\"):
        return root
    p = Path(rel_s)
    parts = rel_s.replace("\\", "/").split("/")
    if p.is_absolute() or p.drive or p.root or rel_s.startswith(("/", "\\")):
        raise PathEscapeError("caminho absoluto não permitido")
    if ".." in parts:
        raise PathEscapeError("'..' não permitido")
    if os.name == "nt" and any(":" in part for part in parts):
        raise PathEscapeError("caminho inválido")
    target = (root / p).resolve()
    if not _is_within(root, target):
        raise PathEscapeError("o caminho sai do diretório do projeto")
    return target


def list_dir(project_path: str, rel: str = "", cap: int = LIST_CAP) -> dict:
    root = Path(project_path).resolve()
    d = safe_join(root, rel)
    if not d.is_dir():
        raise ProjectError("não é um diretório")
    entries, truncated = [], False
    with os.scandir(d) as it:
        for e in sorted(it, key=lambda x: (not x.is_dir(follow_symlinks=False), x.name.lower())):
            try:
                real = Path(e.path).resolve()
            except OSError:
                continue
            if not _is_within(root, real):  # symlink pointing outside: hide it entirely
                continue
            if len(entries) >= cap:
                truncated = True
                break
            try:
                is_dir = e.is_dir()
                size = None if is_dir else e.stat().st_size
            except OSError:
                continue
            entries.append({"name": e.name, "type": "dir" if is_dir else "file", "size": size,
                            "path": real.relative_to(root).as_posix()})
    return {"path": "" if d == root else d.relative_to(root).as_posix(), "entries": entries,
            "truncated": truncated}


def search_names(project_path: str, q: str, rel: str = "", cap: int = SEARCH_CAP) -> dict:
    """Case-insensitive substring search on file/dir names. Never follows symlinks."""
    root = Path(project_path).resolve()
    base = safe_join(root, rel)
    needle = q.lower()
    results, truncated, scanned = [], False, 0
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(n for n in dirnames if n not in SKIP_DIRS)
        for name in sorted(dirnames) + sorted(filenames):
            scanned += 1
            if scanned > SCAN_CAP:
                truncated = True
                break
            if needle in name.lower():
                full = Path(dirpath) / name
                if len(results) >= cap:
                    truncated = True
                    break
                results.append({"name": name, "path": full.relative_to(root).as_posix(),
                                "type": "dir" if full.is_dir() else "file"})
        if truncated:
            break
    return {"query": q, "results": results, "truncated": truncated}


def search_content(project_path: str, q: str, rel: str = "", cap: int = CONTENT_RESULT_CAP,
                   max_file_bytes: int = CONTENT_MAX_FILE_BYTES, max_total_bytes: int = CONTENT_MAX_TOTAL_BYTES,
                   max_seconds: float = CONTENT_MAX_SECONDS, clock=time.monotonic) -> dict:
    """Case-insensitive substring search inside text files (T10.8).

    Skips SKIP_DIRS, symlinks (files and dirs, never followed), files over `max_file_bytes` and
    binaries (NUL byte or invalid UTF-8 in the first 8 KB). Stops, flagging `truncated`, at `cap`
    matches, `max_total_bytes` read or `max_seconds` elapsed. Each hit: path, line (1-based), a
    snippet of at most SNIPPET_CHARS characters around the match.
    """
    root = Path(project_path).resolve()
    base = safe_join(root, rel)
    needle = q.lower()
    if not needle:
        return {"query": q, "mode": "content", "results": [], "truncated": False, "files_scanned": 0,
                "bytes_scanned": 0}
    results: list[dict] = []
    truncated = False
    files_scanned = bytes_scanned = 0
    deadline = clock() + max_seconds
    stack_walk = [base] if base.is_file() else None

    def walk():
        if stack_walk:
            yield str(base.parent), [], [base.name]
            return
        yield from os.walk(base, followlinks=False)

    for dirpath, dirnames, filenames in walk():
        dirnames[:] = sorted(n for n in dirnames if n not in SKIP_DIRS
                             and not os.path.islink(os.path.join(dirpath, n)))
        for name in sorted(filenames):
            if clock() > deadline or bytes_scanned >= max_total_bytes:
                truncated = True
                break
            full = os.path.join(dirpath, name)
            try:
                if os.path.islink(full):
                    continue
                size = os.stat(full).st_size
                if size > max_file_bytes or not _is_within(root, Path(full).resolve()):
                    continue
                with open(full, "rb") as f:
                    data = f.read(max_file_bytes + 1)
            except OSError:
                continue
            if len(data) > max_file_bytes or _looks_binary(data):
                continue
            files_scanned += 1
            bytes_scanned += len(data)
            text = data.decode("utf-8", "replace")
            rel_path = Path(full).relative_to(root).as_posix()
            for lineno, line in enumerate(text.splitlines(), 1):
                idx = line.lower().find(needle)
                if idx < 0:
                    continue
                if len(results) >= cap:
                    truncated = True
                    break
                results.append({"path": rel_path, "line": lineno, "snippet": _snippet(line, idx, len(needle))})
            if truncated:
                break
        if truncated:
            break
    return {"query": q, "mode": "content", "results": results, "truncated": truncated,
            "files_scanned": files_scanned, "bytes_scanned": bytes_scanned}


def _looks_binary(data: bytes) -> bool:
    head = data[:8192]
    if b"\x00" in head:
        return True
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        return e.start < len(head) - 4  # a multi-byte char cut at the sniff boundary is fine
    return False


def _snippet(line: str, idx: int, n: int) -> str:
    start = max(0, idx - SNIPPET_CHARS // 3)
    s = line[start:start + SNIPPET_CHARS].strip()
    return ("…" if start > 0 else "") + s + ("…" if start + SNIPPET_CHARS < len(line) else "")


class ProjectRegistry:
    """Registered projects in `<user_data_dir>/anamnesia.db`, table `projects`. Removing a project
    only deletes the registry row, never any file."""

    def __init__(self, db_path: str | os.PathLike | None = None):
        if db_path is None:
            from config.paths import user_data_dir

            db_path = user_data_dir() / "anamnesia.db"
        self.db_path = Path(db_path)
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        c = self._conn()
        try:
            c.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                      " path TEXT NOT NULL UNIQUE, created_at REAL NOT NULL)")
            c.commit()
        finally:
            c.close()

    @staticmethod
    def _row(r) -> Project:
        return Project(r["id"], r["name"], r["path"], r["created_at"])

    def add(self, name: str, path: str) -> Project:
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise ProjectError("nome obrigatório (até 120 caracteres)")
        try:
            real = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as e:
            raise ProjectError("o caminho não existe") from e
        if not real.is_dir():
            raise ProjectError("o caminho não é um diretório")
        proj = Project(uuid.uuid4().hex[:12], name, str(real), time.time())
        c = self._conn()
        try:
            c.execute("INSERT INTO projects (id,name,path,created_at) VALUES (?,?,?,?)",
                      (proj.id, proj.name, proj.path, proj.created_at))
            c.commit()
        except sqlite3.IntegrityError as e:
            raise ProjectError("esse diretório já está registrado") from e
        finally:
            c.close()
        return proj

    def list(self) -> list[Project]:
        c = self._conn()
        try:
            return [self._row(r) for r in c.execute("SELECT * FROM projects ORDER BY created_at, id")]
        finally:
            c.close()

    def get(self, project_id: str) -> Project | None:
        c = self._conn()
        try:
            r = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            return self._row(r) if r else None
        finally:
            c.close()

    def remove(self, project_id: str) -> bool:
        c = self._conn()
        try:
            n = c.execute("DELETE FROM projects WHERE id=?", (project_id,)).rowcount
            c.commit()
            return n > 0
        finally:
            c.close()
