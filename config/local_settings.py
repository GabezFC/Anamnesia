"""User-local runtime settings (proposta 2026-09-28 §1.2, §1.4, §3).

Persisted in `config/local_settings.json` (gitignored, never inside the vault). Written by the
interactive configuration page, read by the verdict flag (config/optimizer.py) and by the optional
retrieval stages (config/optimization.py). Every key is optional; a missing or malformed file is
never an error. Schema:

    {"verdict_enabled": bool, "optional_stages": {"<stage name>": bool}}
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from config import PROJECT_ROOT

LOCAL_SETTINGS_PATH = PROJECT_ROOT / "config" / "local_settings.json"
_LOCK = threading.Lock()


def _path() -> Path:
    # Module attribute (not a constant captured at import) so tests can monkeypatch it.
    # config/optimizer.py reads the same file for the verdict flag.
    return Path(LOCAL_SETTINGS_PATH)


def load() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save(data: dict) -> dict:
    """Atomic write (temp file + os.replace). Returns what was written."""
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".local_settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    return data


def update(**changes) -> dict:
    data = load()
    for k, v in changes.items():
        if k == "optional_stages" and isinstance(v, dict):
            cur = data.get("optional_stages") if isinstance(data.get("optional_stages"), dict) else {}
            cur.update({str(n): bool(b) for n, b in v.items()})
            data["optional_stages"] = cur
        else:
            data[k] = v
    return save(data)


def get_verdict_enabled() -> bool | None:
    v = load().get("verdict_enabled")
    return v if isinstance(v, bool) else None


def get_optional_stages() -> dict[str, bool]:
    v = load().get("optional_stages")
    if not isinstance(v, dict):
        return {}
    return {str(k): b for k, b in v.items() if isinstance(b, bool)}
