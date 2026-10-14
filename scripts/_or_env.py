"""Load OPENROUTER_* from the Hermes .env into THIS process env only (values are never printed/logged)."""
from __future__ import annotations
import os
from pathlib import Path

ENV = Path(os.environ.get("HERMES_ENV_FILE") or str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "hermes" / ".env"))


def load() -> bool:
    if not ENV.exists():
        return False
    for ln in ENV.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln.startswith("OPENROUTER_") and "=" in ln:
            k, v = ln.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return bool(os.environ.get("OPENROUTER_API_KEY"))
