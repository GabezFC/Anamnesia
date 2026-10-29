"""ANA-102 (EXPERIMENT, flag OFF): persistent FTS5 index updated per note (mtime/size, then sha256).

`IncrementalBaselineIndex` is a drop-in `BaselineIndex` whose FTS table lives in an on-disk SQLite
file (never inside the vault). `build()` stats every searchable note, re-reads only the ones whose
(mtime_ns, size) changed (and re-indexes only if the content hash changed too), and deletes rows of
removed notes. The query side is inherited unchanged (same `sec` table, same bm25 weights).

Enabled only with `MG_INCREMENTAL_INDEX=1` via `make_baseline_index()`; the default path keeps the
in-memory `BaselineIndex`. Verdict (PROMOTE/HOLD) lives in Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24/reports/ANA102_INCREMENTAL_INDEX_*.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault, frontmatter_status, split_sections

SCHEMA_VERSION = "2"
_FTS = ("CREATE VIRTUAL TABLE IF NOT EXISTS sec USING fts5(file UNINDEXED, section, body, status UNINDEXED,"
        " line UNINDEXED, tokenize = 'unicode61 remove_diacritics 2')")
_NOTES = ("CREATE TABLE IF NOT EXISTS notes (file TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER, sha TEXT, r0 INTEGER, r1 INTEGER)")
_META = "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)"


def incremental_enabled() -> bool:
    return os.environ.get("MG_INCREMENTAL_INDEX", "").strip().lower() in ("1", "true", "yes", "on")


class IncrementalBaselineIndex(BaselineIndex):
    def __init__(self, vault: ObsidianVault, db_path: Path | str):
        super().__init__(vault)
        self.db_path = Path(db_path)
        self.last_stats: dict = {}

    def _corpus_identity(self) -> str:
        """Bind persisted rows to the resolved corpus, not just relative note stats."""
        def canonical(path: Path) -> str:
            return os.path.normcase(str(Path(path).resolve()))

        return json.dumps({
            "root": canonical(self.vault.root),
            "extra_roots": {prefix: canonical(root)
                            for prefix, root in self.vault.extra_roots.items()},
            "excluded_dirs": sorted(self.vault.excluded_dirs),
        }, sort_keys=True, ensure_ascii=False)

    def _open(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(_META)
        row = conn.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
        identity = self._corpus_identity()
        corpus = conn.execute("SELECT v FROM meta WHERE k='corpus'").fetchone()
        has_index = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name IN ('sec', 'notes') LIMIT 1"
        ).fetchone() is not None
        if (corpus is not None and corpus[0] != identity) or (corpus is None and has_index):
            conn.close()
            raise ValueError("Persistent index corpus identity mismatch or missing; use a new index database")
        if row is not None and row[0] != SCHEMA_VERSION:
            conn.close()
            raise ValueError("Persistent index schema mismatch; use a new index database")
        conn.execute(_FTS)
        conn.execute(_NOTES)
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (SCHEMA_VERSION,))
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('corpus', ?)", (identity,))
        return conn

    def _stat(self, rel: str) -> tuple[int, int]:
        st = os.stat(self.vault._abs(rel))
        return st.st_mtime_ns, st.st_size

    def close(self) -> None:
        with self._lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    def build(self) -> None:
        conn = self._open()
        known = {r[0]: r[1:] for r in conn.execute("SELECT file, mtime_ns, size, sha, r0, r1 FROM notes")}
        files = self.vault.list_searchable()
        seen = set(files)
        stats = {"files": len(files), "reindexed": 0, "unchanged": 0, "touched_same_hash": 0, "removed": 0}
        with conn:
            for rel in files:
                try:
                    mt, sz = self._stat(rel)
                except OSError:
                    continue
                old = known.get(rel)
                if old and old[0] == mt and old[1] == sz:
                    stats["unchanged"] += 1
                    continue
                text = self.vault.read(rel)
                sha = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
                if old and old[2] == sha:  # mtime moved, content did not
                    conn.execute("UPDATE notes SET mtime_ns=?, size=? WHERE file=?", (mt, sz, rel))
                    stats["touched_same_hash"] += 1
                    continue
                if old and old[3] is not None:  # delete by rowid range: a WHERE on UNINDEXED file is a full scan
                    conn.execute("DELETE FROM sec WHERE rowid BETWEEN ? AND ?", (old[3], old[4]))
                status = frontmatter_status(text) or ""
                r0 = r1 = None
                for s in split_sections(text):
                    cur = conn.execute("INSERT INTO sec VALUES (?,?,?,?,?)", (rel, s.heading_path, s.text, status, s.line))
                    r0 = cur.lastrowid if r0 is None else r0
                    r1 = cur.lastrowid
                conn.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?)", (rel, mt, sz, sha, r0, r1))
                stats["reindexed"] += 1
            for rel in set(known) - seen:
                if known[rel][3] is not None:
                    conn.execute("DELETE FROM sec WHERE rowid BETWEEN ? AND ?", (known[rel][3], known[rel][4]))
                conn.execute("DELETE FROM notes WHERE file=?", (rel,))
                stats["removed"] += 1
        n = conn.execute("SELECT COUNT(*) FROM sec").fetchone()[0]
        with self._lock:
            old_conn, self.conn = self.conn, conn
            self.sections_indexed = n
            self.files_indexed = len(files)
        if old_conn is not None:
            old_conn.close()
        self.last_stats = stats


def make_baseline_index(vault: ObsidianVault, db_path: Path | str | None = None) -> BaselineIndex:
    """Factory: in-memory `BaselineIndex` unless MG_INCREMENTAL_INDEX=1 (ANA-102, default OFF)."""
    if incremental_enabled() and db_path is not None:
        return IncrementalBaselineIndex(vault, db_path)
    return BaselineIndex(vault)
