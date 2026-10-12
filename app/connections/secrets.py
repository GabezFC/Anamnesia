"""Secret storage for connections: the `.env` under user_data_dir (via security.ENV_PATH).

Values are never logged, returned or raised in messages. Only `masked()` exposes anything, and it
exposes the last 4 chars only when the secret is at least 12 chars long.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from app.services import security
from app.services.envfile import EnvValueError, read_env_lines, set_env_var

MASK = "\u2022" * 8
audit = logging.getLogger("anamnesia.secrets.audit")  # ANA-053: key NAMES only, never values
SERVICE = "anamnesia"


def _keyring():
    """ANA-053: the `keyring` module when MG_SECRETS_BACKEND=keyring and it is importable, else None
    (the .env file stays the fallback and the default)."""
    if os.environ.get("MG_SECRETS_BACKEND", "").strip().lower() != "keyring":
        return None
    try:
        import keyring  # type: ignore
        return keyring
    except Exception:  # noqa: BLE001
        audit.warning("secrets backend keyring solicitado mas indisponivel; usando .env")
        return None


class SecretError(ValueError):
    pass


def _path() -> Path:
    return security.ENV_PATH  # looked up at call time so tests can monkeypatch it


def _read(env_key: str) -> str | None:
    val = os.environ.get(env_key)
    if val:
        return val
    kr = _keyring()
    if kr is not None:
        try:
            got = kr.get_password(SERVICE, env_key)
            if got:
                audit.info("secret_get key=%s backend=keyring", env_key)
                return got
        except Exception:  # noqa: BLE001
            pass
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
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, env_key, value)
            audit.info("secret_set key=%s backend=keyring", env_key)
            os.environ[env_key] = value
            return
        except Exception:  # noqa: BLE001
            audit.warning("keyring set falhou key=%s; usando .env", env_key)
    try:
        set_env_var(_path(), env_key, value)  # ANA-006: same validator as /config/model-key
    except EnvValueError as exc:
        raise SecretError(str(exc)) from None
    audit.info("secret_set key=%s backend=env", env_key)
    os.environ[env_key] = value


def delete_key(env_key: str) -> bool:
    """Remove from .env (and keyring when active) and the process env. Returns True if something was removed."""
    kr = _keyring()
    kr_removed = False
    if kr is not None:
        try:
            kr.delete_password(SERVICE, env_key)
            kr_removed = True
        except Exception:  # noqa: BLE001
            pass
    audit.info("secret_delete key=%s", env_key)
    path = _path()
    prefix = f"{env_key}="
    lines = read_env_lines(path)
    kept = [ln for ln in lines if not ln.startswith(prefix)]
    removed = len(kept) != len(lines) or kr_removed
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
