"""Declarative connections catalog loaded from config/connections.yaml (no PyYAML).

Detection is offline-only: `shutil.which` / env var presence / importability. No network.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.routing.registry import RegistryError, _parse_yaml
from config.paths import PACKAGE_ROOT

CATALOG_PATH = PACKAGE_ROOT / "config" / "connections.yaml"
TYPES = ("agent", "model", "mcp")
STATUSES = ("available", "planned")
SNIPPET_FORMATS = ("hermes_yaml", "claude_json", "codex_toml")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class Connection:
    id: str
    type: str
    name: str
    command: str | None
    env_keys: tuple[str, ...]
    docs_url: str | None
    status: str
    mcp_snippet: str | None

    def public(self) -> dict:
        return {"id": self.id, "type": self.type, "name": self.name, "command": self.command,
                "env_keys": list(self.env_keys), "docs_url": self.docs_url, "status": self.status,
                "mcp_snippet": self.mcp_snippet}


def _entry(raw, idx: int) -> Connection:
    where = f"connections[{idx}]"
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: must be a mapping")
    for f in ("id", "type", "name", "status"):
        if not raw.get(f) or not isinstance(raw[f], str):
            raise CatalogError(f"{where}: missing or invalid field {f!r}")
    cid = raw["id"]
    where = f"connection {cid!r}"
    if not _ID_RE.match(cid):
        raise CatalogError(f"{where}: invalid id")
    if raw["type"] not in TYPES:
        raise CatalogError(f"{where}: type must be one of {TYPES}, got {raw['type']!r}")
    if raw["status"] not in STATUSES:
        raise CatalogError(f"{where}: status must be one of {STATUSES}, got {raw['status']!r}")
    env_keys = raw.get("env_keys") or []
    if not isinstance(env_keys, list) or not all(isinstance(k, str) and _ENV_RE.match(k) for k in env_keys):
        raise CatalogError(f"{where}: env_keys must be a list of UPPER_CASE names")
    if len(set(env_keys)) != len(env_keys):
        raise CatalogError(f"{where}: duplicate env_keys")
    command = raw.get("command")
    if command is not None and not isinstance(command, str):
        raise CatalogError(f"{where}: command must be a string or null")
    docs = raw.get("docs_url")
    if docs is not None and not (isinstance(docs, str) and docs.startswith(("http://", "https://"))):
        raise CatalogError(f"{where}: docs_url must be an http(s) URL or null")
    snip = raw.get("mcp_snippet")
    if snip is not None and snip not in SNIPPET_FORMATS:
        raise CatalogError(f"{where}: mcp_snippet must be one of {SNIPPET_FORMATS} or null")
    return Connection(cid, raw["type"], raw["name"], command, tuple(env_keys), docs, raw["status"], snip)


def load_catalog(path: Path | str | None = None) -> list[Connection]:
    p = Path(path) if path is not None else CATALOG_PATH
    try:
        data = _parse_yaml(p.read_text(encoding="utf-8"))
    except RegistryError as e:
        raise CatalogError(f"{p.name}: {e}") from e
    except OSError as e:
        raise CatalogError(f"cannot read {p}: {e}") from e
    items = data.get("connections") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise CatalogError("top-level 'connections' list is required and must be non-empty")
    out, seen = [], set()
    for i, raw in enumerate(items):
        c = _entry(raw, i)
        if c.id in seen:
            raise CatalogError(f"duplicate connection id {c.id!r}")
        seen.add(c.id)
        out.append(c)
    return out


def get_connection(cid: str, path: Path | str | None = None) -> Connection | None:
    return next((c for c in load_catalog(path) if c.id == cid), None)


def detect(c: Connection) -> bool:
    """Offline detection: binary on PATH, any env_key present, or (mcp) module importable."""
    if c.type == "mcp":
        try:
            return importlib.util.find_spec("app.mcp.server") is not None
        except (ImportError, ValueError):
            return False
    if c.command and shutil.which(c.command.split()[0]):
        return True
    return any(os.environ.get(k) for k in c.env_keys)
