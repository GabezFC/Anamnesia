"""Secret storage for connections: the `.env` under user_data_dir (via security.ENV_PATH).

Values are never logged, returned or raised in messages. Only `masked()` exposes anything, and it
exposes the last 4 chars only when the secret is at least 12 chars long.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from app.services import security
from app.services.envfile import read_env_lines, set_env_var

MASK = "\u2022" * 8


class SecretError(ValueError):
    pass


def _path() -> Path:
    return security.ENV_PATH  # looked up at call time so tests can monkeypatch it


def _read(env_key: str) -> str | None:
    val = os.environ.get(env_key)
    if val:
        return val
    prefix = f"{env_key}="
    for line in read_env_lines(_path()):
        if line.startswith(prefix):
            return line[len(prefix):].strip().strip("'\"") or None
    return None


def has_key(env_key: str) -> bool:
    return bool(_read(env_key))


def masked(env_key: str) -> str | None:
    val = _read(env_key)
    if not val:
        return None
    return f"{MASK}{val[-4:]}" if len(val) >= 12 else MASK


def set_key(env_key: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SecretError("value must be a non-empty string")
    if any(ch in value for ch in "\r\n\x00"):
        raise SecretError("value must not contain line breaks")
    value = value.strip()
    set_env_var(_path(), env_key, value)
    os.environ[env_key] = value


def delete_key(env_key: str) -> bool:
    """Remove from .env and the process env. Returns True if something was removed."""
    path = _path()
    prefix = f"{env_key}="
    lines = read_env_lines(path)
    kept = [ln for ln in lines if not ln.startswith(prefix)]
    removed = len(kept) != len(lines)
    if removed:
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write("\n".join(kept) + "\n" if kept else "")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    if os.environ.pop(env_key, None) is not None:
        removed = True
    return removed
