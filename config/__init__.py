"""Domain configuration, read from environment (.env). No secrets are stored here."""
import os

from dotenv import load_dotenv

from config.paths import PACKAGE_ROOT, env_file_path

PROJECT_ROOT = PACKAGE_ROOT  # read-only resources; writable state: see config/paths.py
load_dotenv(env_file_path(), override=False)


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
