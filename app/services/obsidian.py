"""Read-only access to the Obsidian vault (§8, §57).

This is the ONLY module allowed to touch the vault. It exposes read operations only:
there is no write/delete/rename function anywhere in the codebase.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

READ_ONLY_OPERATIONS = frozenset({"list", "read", "stat", "hash"})


class VaultAccessError(PermissionError):
    pass


@dataclass
class Section:
    heading_path: str
    text: str
    line: int


class ObsidianVault:
    def __init__(self, vault_path: Path | str, excluded_dirs: tuple[str, ...] = (".obsidian", ".trash", ".git")):
        self.root = Path(vault_path).resolve()
        self.excluded_dirs = set(excluded_dirs)

    # -- guards -------------------------------------------------------------
    def _guard(self, operation: str, path: Path | None = None) -> Path | None:
        if operation not in READ_ONLY_OPERATIONS:
            raise VaultAccessError(f"Operação '{operation}' não permitida: vault é READ ONLY")
        if path is None:
            return None
        resolved = (self.root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise VaultAccessError(f"Caminho fora do vault configurado: {path}")
        return resolved

    def exists(self) -> bool:
        return self.root.is_dir()

    # -- read operations ----------------------------------------------------
    def list_all(self) -> list[str]:
        """Every non-hidden file, any extension. Read-only, same walk as `list_markdown`."""
        self._guard("list")
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.excluded_dirs and not d.startswith(".")]
            for fn in filenames:
                if fn.startswith("."):
                    continue
                out.append(Path(dirpath, fn).relative_to(self.root).as_posix())
        return sorted(out)

    def list_markdown(self) -> list[str]:
        return [rel for rel in self.list_all() if rel.lower().endswith(".md")]

    def read(self, rel_path: str) -> str:
        p = self._guard("read", Path(rel_path))
        with open(p, "r", encoding="utf-8", errors="replace") as fh:  # read-only mode
            return fh.read()

    def fingerprint(self) -> tuple:
        """Cheap change detector: (count, total bytes, newest mtime, hash of the path list).

        Stat only — no file content is read. Used by the optimization layer to decide when the
        lexical index is stale (measured: ~8 ms for 90 notes, ~33 ms for 520 on NTFS). The path
        hash catches renames/moves, which keep count, size and mtime unchanged.
        """
        self._guard("stat")
        n = size = 0
        newest = 0.0
        paths = hashlib.sha256()
        for rel in self.list_markdown():
            st = os.stat(self.root / rel)
            n += 1
            size += st.st_size
            newest = max(newest, st.st_mtime)
            paths.update(rel.encode("utf-8") + b"\n")
        return (n, size, round(newest, 3), paths.hexdigest()[:16])

    def state_hash(self) -> dict[str, str]:
        """sha256 per markdown file — used to prove nothing was modified (§110)."""
        self._guard("hash")
        result = {}
        for rel in self.list_markdown():
            p = self._guard("read", Path(rel))
            with open(p, "rb") as fh:
                result[rel] = hashlib.sha256(fh.read()).hexdigest()
        return result

    @staticmethod
    def digest(state: dict[str, str]) -> str:
        h = hashlib.sha256()
        for k in sorted(state):
            h.update(f"{k}:{state[k]}\n".encode())
        return h.hexdigest()


_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def split_frontmatter(text: str) -> tuple[str, str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return "", text
    return m.group(0), text[m.end():]


def split_sections(text: str) -> list[Section]:
    """Split markdown into heading-delimited sections, preserving heading hierarchy (§16).

    Headings inside fenced code blocks are ignored so code stays intact.
    """
    fm, body = split_frontmatter(text)
    offset = fm.count("\n")
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    start = offset + 1
    in_fence = False

    def flush():
        content = "\n".join(buf).strip()
        if content:
            path = " > ".join(h for _, h in stack) or "(início)"
            sections.append(Section(path, content, start))

    for i, line in enumerate(body.split("\n"), start=offset + 1):
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            buf = []
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            start = i
            buf.append(line)
        else:
            buf.append(line)
    flush()
    return sections


def frontmatter_status(text: str) -> str | None:
    fm, _ = split_frontmatter(text)
    m = re.search(r"^status:\s*(\S+)", fm, re.M)
    return m.group(1) if m else None


_FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")
# YAML null spellings, so `projeto: null` never becomes the project literally named "null".
_FM_NULL = {"", "null", "none", "~", "nil"}
_FM_TRUE = {"true", "yes", "on"}
_FM_FALSE = {"false", "no", "off"}


def frontmatter_fields(text: str) -> dict:
    """Parse the note's YAML-ish frontmatter into a plain dict (deterministic, no yaml dependency).

    Only what the vault actually uses is supported: `key: value`, inline `[a, b]` lists and quoted
    scalars. Nested mappings and block lists are NOT parsed -- an unparseable line is skipped, so a
    richer frontmatter degrades to "that field is missing" instead of raising. Every consumer that
    needs frontmatter values (the memory audit, the provenance line) parses it HERE so the two can
    never disagree about what a note declares.
    """
    fm, _ = split_frontmatter(text)
    out: dict = {}
    if not fm or not fm.startswith("---"):
        return out
    for line in fm.splitlines()[1:]:
        if line.strip() == "---":
            break
        m = _FM_KEY.match(line)
        if not m:
            continue
        key, value = m.group(1).strip().lower(), m.group(2).strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [i.strip().strip("'\"") for i in inner.split(",") if i.strip()] if inner else []
            continue
        low = value.lower()
        if low in _FM_NULL:
            out[key] = None
        elif low in _FM_TRUE:
            out[key] = True
        elif low in _FM_FALSE:
            out[key] = False
        else:
            out[key] = value
    return out
