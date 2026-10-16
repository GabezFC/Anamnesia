"""ANAM-026: backup/restore of the memory store (saved_context/*.md) and benchmark.db.

Format: one ``.zip`` with ``manifest.json`` (sha256 + size per member) and the payload:
``benchmark.db`` (consistent copy via the sqlite3 backup API, so WAL content is included) and
``memory/<relative path>`` for every file of the memory store.

Restore verifies every sha256 *before* writing anything and never overwrites an existing
target unless ``force=True``. Pure stdlib; touches only the paths it is given.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "manifest.json"
DB_MEMBER = "benchmark.db"
MEMORY_PREFIX = "memory/"
FORMAT_VERSION = 1


class BackupError(Exception):
    """Integrity failure, bad archive or refusal to overwrite."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_snapshot(db: Path) -> bytes:
    """Consistent copy of a (possibly WAL-mode, possibly open) SQLite DB, read-only on the source."""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return Path(tmp).read_bytes()
    finally:
        Path(tmp).unlink(missing_ok=True)


def create_backup(out: Path, db: Path | None = None, memory_dir: Path | None = None, *, force: bool = False) -> dict:
    out = Path(out)
    if out.exists() and not force:
        raise BackupError(f"{out} já existe (use --force para sobrescrever)")
    members: dict[str, bytes] = {}
    if db is not None:
        db = Path(db)
        if not db.is_file():
            raise BackupError(f"banco não encontrado: {db}")
        members[DB_MEMBER] = _sqlite_snapshot(db)
    if memory_dir is not None:
        memory_dir = Path(memory_dir)
        if not memory_dir.is_dir():
            raise BackupError(f"memory store não encontrado: {memory_dir}")
        for p in sorted(memory_dir.rglob("*")):
            if p.is_file():
                members[MEMORY_PREFIX + p.relative_to(memory_dir).as_posix()] = p.read_bytes()
    if not members:
        raise BackupError("nada para copiar (informe db e/ou memory_dir)")
    manifest = {
        "format": FORMAT_VERSION,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": [{"name": n, "sha256": _sha256_bytes(d), "size": len(d)} for n, d in members.items()],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(manifest, indent=2))
        for n, d in members.items():
            z.writestr(n, d)
    os.replace(tmp, out)
    return {"archive": str(out), "archive_sha256": _sha256_file(out), "files": len(members),
            "bytes": sum(len(d) for d in members.values())}


def verify_backup(archive: Path) -> dict:
    """Raise BackupError unless every member matches the manifest sha256/size and nothing is extra."""
    archive = Path(archive)
    if not archive.is_file():
        raise BackupError(f"backup não encontrado: {archive}")
    try:
        z = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise BackupError(f"arquivo de backup corrompido: {exc}") from exc
    with z:
        try:
            manifest = json.loads(z.read(MANIFEST))
        except (KeyError, ValueError) as exc:
            raise BackupError("manifest.json ausente ou inválido") from exc
        listed = {f["name"]: f for f in manifest.get("files", [])}
        actual = set(z.namelist()) - {MANIFEST}
        if actual != set(listed):
            raise BackupError(f"conteúdo diverge do manifest: {sorted(actual ^ set(listed))}")
        for name, meta in listed.items():
            if name != DB_MEMBER and not name.startswith(MEMORY_PREFIX):
                raise BackupError(f"membro inesperado: {name}")
            parts = name.split("/")
            if name.startswith("/") or ".." in parts or ":" in name:
                raise BackupError(f"caminho inseguro: {name}")
            data = z.read(name)
            if len(data) != meta["size"] or _sha256_bytes(data) != meta["sha256"]:
                raise BackupError(f"sha256 não confere: {name}")
    return manifest


def restore_backup(archive: Path, db: Path | None = None, memory_dir: Path | None = None, *, force: bool = False) -> dict:
    """Restore into ``db`` / ``memory_dir``. All-or-nothing check first; no overwrite without force."""
    manifest = verify_backup(archive)
    names = [f["name"] for f in manifest["files"]]
    has_db = DB_MEMBER in names
    mem = [n for n in names if n.startswith(MEMORY_PREFIX)]
    if has_db and db is None and not mem:
        raise BackupError("o backup contém benchmark.db: informe o destino --db")
    targets: list[tuple[str, Path]] = []
    if has_db and db is not None:
        targets.append((DB_MEMBER, Path(db)))
    if mem and memory_dir is not None:
        root = Path(memory_dir).resolve()
        for n in mem:
            t = (root / n[len(MEMORY_PREFIX):]).resolve()
            if root != t and root not in t.parents:
                raise BackupError(f"caminho fora do destino: {n}")
            targets.append((n, t))
    if not targets:
        raise BackupError("nenhum destino compatível com o conteúdo do backup")
    clashes = [str(t) for _, t in targets if t.exists()]
    if clashes and not force:
        raise BackupError(f"destino já existe (use --force): {clashes[:3]}")
    restored = []
    with zipfile.ZipFile(archive) as z:
        for name, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".restore-part")
            tmp.write_bytes(z.read(name))
            if name == DB_MEMBER:           # stale WAL/SHM would corrupt the restored DB
                for suffix in ("-wal", "-shm"):
                    Path(str(target) + suffix).unlink(missing_ok=True)
            os.replace(tmp, target)
            restored.append(str(target))
    return {"restored": len(restored), "files": restored, "overwrote": bool(clashes)}


__all__ = ["BackupError", "create_backup", "verify_backup", "restore_backup"]
