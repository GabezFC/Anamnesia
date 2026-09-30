"""Atomic `.env` read/write, preserving every unrelated line (§3, §5.4 da proposta 2026-09-28).

Used by the interactive configuration page to persist a model API key or `MEMORY_GATEWAY_VAULT`,
and by app/services/security.py to persist the local write-protection token (`MG_LOCAL_TOKEN`).
Never touches the vault; the file lives at the project root and is gitignored.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()


def read_env_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []


def set_env_var(path: Path, key: str, value: str) -> None:
    """Replace the `KEY=...` line if present, else append one. Every other line is untouched.

    Atomic (temp file + os.replace): a crash mid-write never leaves a half-written `.env`.
    """
    prefix = f"{key}="
    with _LOCK:
        lines = read_env_lines(path)
        out, found = [], False
        for line in lines:
            if line.startswith(prefix):
                out.append(f"{key}={value}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"{key}={value}")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(out) + "\n" if out else "")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
