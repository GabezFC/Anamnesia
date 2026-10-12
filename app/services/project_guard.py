"""ANA-026 / P-04: allowlist of roots for POST /api/projects.

A registered project becomes (a) a file-explorer root and (b) the cwd of a terminal, so registering
HOME, a drive root, `~/.ssh` or `AppData` hands an agent the user's secrets. Rules:

  * always refused: a filesystem/drive root, the user's HOME itself, anything inside a sensitive
    directory (.ssh .aws .gnupg .azure .kube .docker .config/gcloud .claude AppData/*, ...), and
    the parent of HOME.  The system temp dir is exempt (tests, scratch projects).
  * `MG_PROJECT_ROOTS` (os.pathsep or comma separated): when set, the project must live inside one
    of those roots (a configured root is the "human confirmation").
Mode (`ANAMNESIA_PROJECT_GUARD`): enforce (default) -> ProjectDenied (HTTP 403) | warn -> allowed,
logged | off.  Rollback is one env var; nothing else changes for ordinary project folders.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("anamnesia.project_guard")

SENSITIVE_DIRS = {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker", ".claude", ".npm", ".gcloud",
                  "appdata"}
_MODES = ("enforce", "warn", "off")


class ProjectDenied(PermissionError):
    pass


def _mode() -> str:
    m = os.environ.get("ANAMNESIA_PROJECT_GUARD", "enforce").strip().lower()
    return m if m in _MODES else "enforce"


def _norm(p: Path) -> str:
    return os.path.normcase(str(p))


def _within(child: Path, root: Path) -> bool:
    c, r = _norm(child), _norm(root).rstrip("\\/")
    return c == r or c.startswith(r + os.sep)


def configured_roots() -> list[Path]:
    raw = os.environ.get("MG_PROJECT_ROOTS", "")
    parts = [x for chunk in raw.split(os.pathsep) for x in chunk.split(",")]
    out = []
    for x in parts:
        x = x.strip()
        if x:
            try:
                out.append(Path(x).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
    return out


def violation(path: Path) -> str | None:
    """Reason the (already resolved) directory must not become a project, or None if acceptable."""
    path = Path(path)
    home = Path.home().resolve()
    try:
        tmp = Path(tempfile.gettempdir()).resolve()
    except OSError:
        tmp = None
    if tmp is not None and _within(path, tmp):
        return None
    if path.parent == path:
        return "raiz de unidade/sistema de arquivos"
    if _norm(path) == _norm(home) or _within(home, path):
        return "diretório HOME do usuário (ou um pai dele)"
    for part in path.parts[1:]:
        if part.lower() in SENSITIVE_DIRS:
            return f"diretório sensível ({part})"
    roots = configured_roots()
    if roots and not any(_within(path, r) for r in roots):
        return "fora das raízes permitidas (MG_PROJECT_ROOTS)"
    return None


def check(path: str | os.PathLike) -> None:
    """Raise ProjectDenied in enforce mode; log in warn mode; no-op when off."""
    mode = _mode()
    if mode == "off":
        return
    try:
        real = Path(path).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return  # a bad path is reported by the registry itself
    why = violation(real)
    if not why:
        return
    if mode == "warn":
        log.warning("project_guard(warn): %s -> %s", real, why)
        return
    raise ProjectDenied(f"projeto recusado: {why}")
