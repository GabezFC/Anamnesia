"""Where user-writable state lives (single source of truth; no directory is created here).

Two roots, never mixed up:
  * PACKAGE_ROOT -- read-only resources shipped with the code (frontend/, data/synthetic_vault,
    config/models.yaml). In a git checkout this is the repo root; in an installed wheel it is
    site-packages.
  * data root (`user_data_dir()`) -- everything the app WRITES: .env (local token), benchmark.db,
    logs/, data/ (mirror, caches), local_settings.json.

Resolution of the data root:
  1. env ANAMNESIA_HOME (always wins);
  2. installed package (no `.git`, root lives under site-packages/dist-packages) -> platform user
     data dir (Windows %LOCALAPPDATA%/Anamnesia, macOS ~/Library/Application Support/Anamnesia,
     Linux $XDG_DATA_HOME/anamnesia or ~/.local/share/anamnesia);
  3. otherwise (git checkout / dev) -> PACKAGE_ROOT, exactly the historical behaviour.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOME_ENV_VAR = "ANAMNESIA_HOME"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def is_installed_layout(root: Path | None = None) -> bool:
    """True when `root` looks like a pip/pipx/uv install rather than a source checkout."""
    root = Path(root) if root is not None else PACKAGE_ROOT
    if (root / ".git").exists():
        return False
    return any(part.lower() in {"site-packages", "dist-packages"} for part in root.parts)


def platform_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Anamnesia"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Anamnesia"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "anamnesia"


def user_data_dir() -> Path:
    """Resolved data root. Pure: never creates anything."""
    override = os.environ.get(HOME_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_installed_layout():
        return platform_data_dir()
    return PACKAGE_ROOT


def env_file_path() -> Path:
    return user_data_dir() / ".env"


def benchmark_db_path() -> Path:
    return user_data_dir() / "benchmark.db"


def logs_dir() -> Path:
    return user_data_dir() / "logs"


def data_dir() -> Path:
    """Writable data/ (vault mirror, caches). Packaged read-only data stays under PACKAGE_ROOT."""
    return user_data_dir() / "data"


def saved_context_dir() -> Path:
    """Gateway-owned Markdown folder for agent-saved context (Fase 7). Never inside the user's vault.

    Dev checkout: <repo>/data/saved_context (covered by the `data/*` rule in .gitignore).
    """
    return data_dir() / "saved_context"


def local_settings_path() -> Path:
    root = user_data_dir()
    # Dev checkout keeps config/local_settings.json where it has always been.
    return root / "config" / "local_settings.json" if root == PACKAGE_ROOT else root / "local_settings.json"
