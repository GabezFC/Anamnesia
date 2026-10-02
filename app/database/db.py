"""SQLite persistence (§58). Database lives in the project (benchmark.db), never in the vault."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from app.schemas.models import DEFAULT_EXPLICIT_PIPELINE

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY, created_at REAL, kind TEXT, config_json TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, session_id TEXT, created_at REAL, question_id TEXT, query TEXT,
  pipeline TEXT, agent TEXT, provider TEXT, model TEXT, mode TEXT, repetition INTEGER,
  warmup INTEGER DEFAULT 0, order_index INTEGER, threshold REAL, jev_mode TEXT, jev_model TEXT,
  cache_enabled INTEGER, config_json TEXT, metrics_json TEXT, sources_json TEXT,
  context TEXT, answer TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id);
CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at);
CREATE INDEX IF NOT EXISTS runs_session_created ON runs(session_id, created_at);
CREATE INDEX IF NOT EXISTS runs_pipeline_warmup ON runs(pipeline, warmup);
CREATE TABLE IF NOT EXISTS candidates (
  run_id TEXT, candidate_id TEXT, source_file TEXT, section TEXT, score REAL,
  relevance REAL, injection REAL, decision TEXT, tokens INTEGER
);
CREATE INDEX IF NOT EXISTS cand_run ON candidates(run_id);
CREATE TABLE IF NOT EXISTS false_negatives (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, run_id TEXT, candidate_id TEXT,
  threshold REAL, jev_score REAL, question TEXT, pipeline TEXT
);
CREATE TABLE IF NOT EXISTS retrieval_labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, run_id TEXT, source_file TEXT,
  label TEXT CHECK(label IN ('relevant_found','relevant_missed','false_negative','false_positive'))
);
CREATE TABLE IF NOT EXISTS evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL, run_id TEXT, question_id TEXT,
  agent TEXT, model TEXT, pipeline TEXT,
  accuracy INTEGER CHECK(accuracy BETWEEN 1 AND 5), completeness INTEGER CHECK(completeness BETWEEN 1 AND 5),
  groundedness INTEGER CHECK(groundedness BETWEEN 1 AND 5), citation_quality INTEGER CHECK(citation_quality BETWEEN 1 AND 5),
  notes TEXT
);
CREATE TABLE IF NOT EXISTS jev_cache (key TEXT PRIMARY KEY, value TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS configs (hash TEXT PRIMARY KEY, json TEXT);
"""
# Columns added after the original schema shipped (§5.3). Added via ALTER TABLE, guarded by
# PRAGMA table_info so existing databases migrate in place without losing data:
#   config_hash       -> dedup key into `configs`; a row keeps EITHER config_json (old rows,
#                        written before this migration) OR config_hash (new rows), never both.
#   context_encoding  -> NULL/"" for plain text (old rows, or compression disabled), "zlib+b64"
#                        when `context` holds base64(zlib(text)).
RUNS_MIGRATED_COLUMNS = (("config_hash", "TEXT"), ("context_encoding", "TEXT"))

LIST_COLUMNS = ("run_id, session_id, created_at, question_id, query, pipeline, agent, provider, model, mode,"
                " repetition, warmup, threshold, jev_mode, error, metrics_json")
FULL_EXTRA_COLUMNS = ", config_json, config_hash, sources_json, context, context_encoding, answer"


class Database:
    def __init__(self, path: str | Path, compress_context: bool = False):
        self.path = str(path)
        # Whether NEW rows get their `context` column zlib-compressed (base64-encoded text, so the
        # column stays TEXT). Reading never depends on this flag: `context_encoding` on each row
        # says how that row was written, so toggling this setting is always retrocompatible.
        self.compress_context = compress_context
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate_columns()

    def _migrate_columns(self) -> None:
        existing = {r["name"] for r in self.query("PRAGMA table_info(runs)")}
        for col, decl in RUNS_MIGRATED_COLUMNS:
            if col not in existing:
                self._exec(f"ALTER TABLE runs ADD COLUMN {col} {decl}")

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # sessions / runs ---------------------------------------------------------
    def create_session(self, session_id: str, kind: str, config: dict, notes: str = "") -> None:
        self._exec("INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?)",
                   (session_id, time.time(), kind, json.dumps(config, default=str), notes))

    def _dedup_config(self, row: dict[str, Any]) -> None:
        """Replace `config_json` (near-identical across runs) with a hash into `configs` (§5.3)."""
        cfg = row.get("config_json")
        if cfg is None:
            row["config_hash"] = None
            return
        cfg_str = cfg if isinstance(cfg, str) else json.dumps(cfg, default=str, ensure_ascii=False)
        digest = hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()
        self._exec("INSERT OR IGNORE INTO configs (hash, json) VALUES (?,?)", (digest, cfg_str))
        row["config_hash"] = digest
        row["config_json"] = None

    def _maybe_compress_context(self, row: dict[str, Any]) -> None:
        ctx = row.get("context")
        if self.compress_context and isinstance(ctx, str) and ctx:
            row["context"] = base64.b64encode(zlib.compress(ctx.encode("utf-8"), 6)).decode("ascii")
            row["context_encoding"] = "zlib+b64"
        else:
            row.setdefault("context_encoding", None)

    def save_run(self, row: dict[str, Any], candidates: list[dict] | None = None) -> None:
        row = dict(row)
        self._dedup_config(row)
        self._maybe_compress_context(row)
        cols = ["run_id", "session_id", "created_at", "question_id", "query", "pipeline", "agent", "provider",
                "model", "mode", "repetition", "warmup", "order_index", "threshold", "jev_mode", "jev_model",
                "cache_enabled", "config_json", "config_hash", "metrics_json", "sources_json",
                "context", "context_encoding", "answer", "error"]
        vals = []
        for c in cols:
            v = row.get(c)
            if c.endswith("_json") and v is not None and not isinstance(v, str):
                v = json.dumps(v, default=str, ensure_ascii=False)
            vals.append(v)
        self._exec(f"INSERT OR REPLACE INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", tuple(vals))
        for cd in candidates or []:
            self._exec("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)",
                       (row["run_id"], cd["candidate_id"], cd["source_file"], cd["section"], cd["score"],
                        cd.get("relevance"), cd.get("injection"), cd.get("decision"), cd.get("token_estimate")))

    def update_run_answer(self, run_id: str, answer: str | None, metrics: dict, error: str | None = None) -> None:
        self._exec("UPDATE runs SET answer=?, metrics_json=?, error=? WHERE run_id=?",
                   (answer, json.dumps(metrics, default=str, ensure_ascii=False), error, run_id))

    def _resolve_config(self, config_hash: str) -> dict | None:
        rows = self.query("SELECT json FROM configs WHERE hash=?", (config_hash,))
        return json.loads(rows[0]["json"]) if rows else None

    def _decode(self, r: dict) -> dict:
        encoding = r.pop("context_encoding", None)
        if encoding == "zlib+b64" and r.get("context"):
            r["context"] = zlib.decompress(base64.b64decode(r["context"])).decode("utf-8")
        config_hash = r.pop("config_hash", None)
        if r.get("config_json"):
            r["config"] = json.loads(r.pop("config_json"))
        else:
            r.pop("config_json", None)
            if config_hash:
                r["config"] = self._resolve_config(config_hash)
        for k in ("metrics_json", "sources_json"):
            if r.get(k):
                r[k[:-5]] = json.loads(r.pop(k))
            else:
                r.pop(k, None)
        return r

    def get_run(self, run_id: str) -> dict | None:
        rows = self.query("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if not rows:
            return None
        run = self._decode(rows[0])
        run["candidates"] = self.query("SELECT * FROM candidates WHERE run_id=?", (run_id,))
        return run

    @staticmethod
    def _run_filters(session_id: str | None, agent: str | None, q: str | None, since: float | None,
                      adhoc_only: bool, until: float | None = None) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        args: list[Any] = []
        # adhoc_only is its own tab (session_id == "adhoc"): it wins over an explicit session_id.
        sid = "adhoc" if adhoc_only else session_id
        if sid:
            where.append("session_id=?")
            args.append(sid)
        if agent:
            where.append("agent=?")
            args.append(agent)
        if since is not None:
            where.append("created_at>=?")
            args.append(since)
        if until is not None:
            where.append("created_at<=?")
            args.append(until)
        if q:
            where.append("query LIKE ?")
            args.append(f"%{q}%")
        return where, args

    def list_runs(self, limit: int = 100, offset: int = 0, session_id: str | None = None,
                  agent: str | None = None, q: str | None = None, since: float | None = None,
                  adhoc_only: bool = False, full: bool = False, until: float | None = None) -> list[dict]:
        cols = LIST_COLUMNS + (FULL_EXTRA_COLUMNS if full else "")
        sql = f"SELECT {cols} FROM runs"
        where, args = self._run_filters(session_id, agent, q, since, adhoc_only, until)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        return [self._decode(r) for r in self.query(sql, tuple(args) + (limit, offset))]

    def count_runs(self, session_id: str | None = None, agent: str | None = None, q: str | None = None,
                   since: float | None = None, adhoc_only: bool = False, until: float | None = None) -> int:
        sql = "SELECT COUNT(*) n FROM runs"
        where, args = self._run_filters(session_id, agent, q, since, adhoc_only, until)
        if where:
            sql += " WHERE " + " AND ".join(where)
        return self.query(sql, tuple(args))[0]["n"]

    # A usable epoch-seconds timestamp: numeric storage class and not in milliseconds.
    _VALID_TS = "typeof(created_at) IN ('real','integer') AND created_at > 0 AND created_at <= 1e12"

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Sessions ordered by LAST ACTIVITY (newest run), not by when the row was first inserted.

        `create_session` is INSERT OR IGNORE, so a long-lived session such as "adhoc" keeps its
        original `created_at` forever; the real recency lives in `runs`. session_ids that exist only
        in `runs` are included too. Recorded timestamps are never altered.
        """
        return self.query(f"""
            WITH agg AS (
              SELECT session_id, COUNT(*) AS runs,
                     MIN(CASE WHEN {self._VALID_TS} THEN created_at END) AS first_run_at,
                     MAX(CASE WHEN {self._VALID_TS} THEN created_at END) AS last_run_at
              FROM runs WHERE session_id IS NOT NULL GROUP BY session_id
            ), allsess AS (
              SELECT s.session_id, s.created_at, s.kind, s.config_json, s.notes,
                     a.first_run_at, a.last_run_at, COALESCE(a.runs, 0) AS runs
              FROM sessions s LEFT JOIN agg a ON a.session_id = s.session_id
              UNION ALL
              SELECT a.session_id, NULL, NULL, NULL, NULL, a.first_run_at, a.last_run_at, a.runs
              FROM agg a WHERE a.session_id NOT IN (SELECT session_id FROM sessions)
            )
            SELECT * FROM allsess
            ORDER BY COALESCE(last_run_at, created_at) DESC, session_id
            LIMIT ? OFFSET ?""", (limit, offset))

    def count_sessions(self) -> int:
        return self.query("""SELECT COUNT(*) n FROM (
            SELECT session_id FROM sessions
            UNION SELECT session_id FROM runs WHERE session_id IS NOT NULL)""")[0]["n"]

    def history_summary(self) -> dict:
        """Observability for the whole history (§35): what is stored, over which span, and what is
        malformed. Counts everything in `runs`, warm-ups and ad-hoc included."""
        valid = self._VALID_TS
        head = self.query(f"""SELECT COUNT(*) AS total_runs,
              SUM(CASE WHEN session_id='adhoc' THEN 1 ELSE 0 END) AS adhoc_runs,
              SUM(CASE WHEN COALESCE(warmup,0)=1 OR mode='warmup' THEN 1 ELSE 0 END) AS warmup_runs,
              SUM(CASE WHEN NOT ({valid}) THEN 1 ELSE 0 END) AS invalid_timestamps,
              MIN(CASE WHEN {valid} THEN created_at END) AS oldest_run_at,
              MAX(CASE WHEN {valid} THEN created_at END) AS newest_run_at FROM runs""")[0]
        per_day = {}
        for label, mod in (("local", "'unixepoch','localtime'"), ("utc", "'unixepoch'")):
            rows = self.query(f"""SELECT date(created_at, {mod}) AS day, COUNT(*) AS runs FROM runs
                                  WHERE {valid} GROUP BY day ORDER BY day""")
            per_day[label] = {r["day"]: r["runs"] for r in rows}
        return {
            "total_runs": head["total_runs"] or 0,
            "total_sessions": self.count_sessions(),
            "oldest_run_at": head["oldest_run_at"],
            "newest_run_at": head["newest_run_at"],
            "runs_por_dia": per_day["local"],
            "runs_por_dia_utc": per_day["utc"],
            "adhoc_runs": head["adhoc_runs"] or 0,
            "warmup_runs": head["warmup_runs"] or 0,
            "invalid_timestamps": head["invalid_timestamps"] or 0,
        }

    def series_rows(self, pipeline: str | None = None) -> list[dict]:
        """Every non-warm-up run reduced to what a time series needs. No cap: the caller filters by
        time AFTER normalising timestamps, because stored values may be seconds, ms or text."""
        sql = ("SELECT run_id, session_id, created_at, pipeline, metrics_json FROM runs"
               " WHERE COALESCE(warmup,0)=0 AND COALESCE(mode,'')<>'warmup'")
        args: tuple = ()
        if pipeline:
            sql += " AND pipeline=?"
            args = (pipeline,)
        return self.query(sql, args)

    # maintenance (§5.3) -------------------------------------------------------
    def prune(self, keep_days: int, keep_sessions: list[str] | None = None, dry_run: bool = False) -> dict:
        """Delete runs (and their candidates) older than `keep_days`. Runs whose session_id is in
        `keep_sessions` are never deleted, regardless of age."""
        cutoff = time.time() - keep_days * 86400
        keep = [s for s in (keep_sessions or []) if s]
        where = "created_at < ?"
        args: list[Any] = [cutoff]
        if keep:
            where += f" AND session_id NOT IN ({','.join('?' * len(keep))})"
            args += keep
        run_ids = [r["run_id"] for r in self.query(f"SELECT run_id FROM runs WHERE {where}", tuple(args))]
        if dry_run:
            return {"would_delete": len(run_ids), "cutoff": cutoff, "dry_run": True}
        self._exec(f"DELETE FROM runs WHERE {where}", tuple(args))
        if run_ids:
            placeholders = ",".join("?" * len(run_ids))
            self._exec(f"DELETE FROM candidates WHERE run_id IN ({placeholders})", tuple(run_ids))
        return {"deleted": len(run_ids), "cutoff": cutoff, "dry_run": False}

    def rewrite_legacy_rows(self, compress_context: bool = False, batch_size: int = 500) -> dict:
        """One-off maintenance pass for a database that predates this migration (§5.3): dedups
        `config_json` into `configs` and, if `compress_context`, zlib-compresses `context` for
        rows that still have it inline. Idempotent (already-migrated rows never match the WHERE
        clause again), so it is safe to run more than once. Not called automatically on open —
        a 100+ MB database would make every startup slow; run it explicitly (e.g. from a
        maintenance script) when adopting the new schema on an existing file.
        """
        configs_deduped = 0
        context_compressed = 0
        where = "config_json IS NOT NULL"
        if compress_context:
            where += " OR (context_encoding IS NULL AND context IS NOT NULL)"
        while True:
            rows = self.query(f"SELECT run_id, config_json, context, context_encoding FROM runs"
                              f" WHERE {where} LIMIT ?", (batch_size,))
            if not rows:
                break
            for r in rows:
                updates: dict[str, Any] = {}
                if r["config_json"] is not None:
                    digest = hashlib.sha256(r["config_json"].encode("utf-8")).hexdigest()
                    self._exec("INSERT OR IGNORE INTO configs (hash, json) VALUES (?,?)", (digest, r["config_json"]))
                    updates["config_hash"] = digest
                    updates["config_json"] = None
                    configs_deduped += 1
                if compress_context and r["context_encoding"] is None and r["context"]:
                    updates["context"] = base64.b64encode(zlib.compress(r["context"].encode("utf-8"), 6)).decode("ascii")
                    updates["context_encoding"] = "zlib+b64"
                    context_compressed += 1
                if updates:
                    set_sql = ", ".join(f"{k}=?" for k in updates)
                    self._exec(f"UPDATE runs SET {set_sql} WHERE run_id=?", (*updates.values(), r["run_id"]))
            if len(rows) < batch_size:
                break
        return {"configs_deduped": configs_deduped, "context_compressed": context_compressed}

    def vacuum(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.execute("VACUUM")

    # feedback ----------------------------------------------------------------
    def mark_false_negative(self, run_id: str, candidate_id: str) -> dict:
        run = self.get_run(run_id)
        if not run:
            raise KeyError(run_id)
        cand = next((c for c in run["candidates"] if c["candidate_id"] == candidate_id), None)
        if not cand:
            raise KeyError(candidate_id)
        row = (time.time(), run_id, candidate_id, run.get("threshold"), cand.get("relevance"), run["query"],
               run["pipeline"])
        self._exec("INSERT INTO false_negatives (created_at, run_id, candidate_id, threshold, jev_score, question,"
                   " pipeline) VALUES (?,?,?,?,?,?,?)", row)
        return {"run_id": run_id, "candidate_id": candidate_id, "threshold": row[3], "jev_score": row[4]}

    def add_label(self, run_id: str, source_file: str, label: str) -> None:
        self._exec("INSERT INTO retrieval_labels (created_at, run_id, source_file, label) VALUES (?,?,?,?)",
                   (time.time(), run_id, source_file, label))

    def add_evaluation(self, ev: dict) -> None:
        self._exec("INSERT INTO evaluations (created_at, run_id, question_id, agent, model, pipeline, accuracy,"
                   " completeness, groundedness, citation_quality, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (time.time(), ev["run_id"], ev.get("question_id"), ev.get("agent"), ev.get("model"),
                    ev.get("pipeline"), ev.get("accuracy"), ev.get("completeness"), ev.get("groundedness"),
                    ev.get("citation_quality"), ev.get("notes")))

    def false_negative_rate(self, pipeline: str = DEFAULT_EXPLICIT_PIPELINE) -> dict:
        dropped = self.query("SELECT COUNT(*) n FROM candidates c JOIN runs r ON r.run_id=c.run_id"
                             " WHERE r.pipeline=? AND c.decision IN ('DROP','QUARANTINE')", (pipeline,))[0]["n"]
        fn = self.query("SELECT COUNT(*) n FROM false_negatives WHERE pipeline=?", (pipeline,))[0]["n"]
        return {"dropped_total": dropped, "false_negatives": fn,
                "false_negative_rate": round(fn / dropped, 4) if dropped else None}

    # cache ---------------------------------------------------------------------
    def cache_get(self, key: str) -> dict | None:
        r = self.query("SELECT value FROM jev_cache WHERE key=?", (key,))
        return json.loads(r[0]["value"]) if r else None

    def cache_put(self, key: str, value: dict) -> None:
        self._exec("INSERT OR REPLACE INTO jev_cache VALUES (?,?,?)", (key, json.dumps(value), time.time()))
