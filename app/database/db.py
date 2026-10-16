"""SQLite persistence (§58). Database lives in the project (benchmark.db), never in the vault."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import queue
import sqlite3
import threading
import time
import zlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.database.migrations import BENCHMARK_MIGRATIONS, run_migrations
from app.schemas.models import DEFAULT_EXPLICIT_PIPELINE

log = logging.getLogger("anamnesia.db")


def _env_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}

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
-- ANA-134: runs_session (prefix of runs_session_created) and runs_created (== runs_created_at) are
-- gone: migration 2 drops them from existing files and they are no longer created here.
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
CREATE TABLE IF NOT EXISTS budgets (period TEXT PRIMARY KEY, ceiling_usd REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS routing_decisions (
  run_id TEXT, policy_version TEXT, registry_version TEXT, complexity REAL, risk TEXT, tier INTEGER,
  model TEXT, effort TEXT, verify TEXT, reason_codes TEXT, router_tokens INTEGER, router_cost REAL,
  latency_ms REAL
);
CREATE INDEX IF NOT EXISTS routing_decisions_run ON routing_decisions(run_id);
CREATE TABLE IF NOT EXISTS verification_results (
  run_id TEXT, attempt INTEGER, level TEXT, passed INTEGER, tokens INTEGER, cost REAL, failure_code TEXT
);
CREATE INDEX IF NOT EXISTS verification_results_run ON verification_results(run_id);
"""
# Columns added after the original schema shipped (§5.3). Added via ALTER TABLE, guarded by
# PRAGMA table_info so existing databases migrate in place without losing data:
#   config_hash       -> dedup key into `configs`; a row keeps EITHER config_json (old rows,
#                        written before this migration) OR config_hash (new rows), never both.
#   context_encoding  -> NULL/"" for plain text (old rows, or compression disabled), "zlib+b64"
#                        when `context` holds base64(zlib(text)).
#   project / terminal_session_id / cost_origin -> per-call cost ledger (Anamnesia "Custos"):
#                        project from the search scope, terminal session from env MG_TERMINAL_SESSION,
#                        cost_origin = measured | estimated | unavailable.
RUNS_MIGRATED_COLUMNS = (("config_hash", "TEXT"), ("context_encoding", "TEXT"),
                         ("project", "TEXT"), ("terminal_session_id", "TEXT"), ("cost_origin", "TEXT"),
                         # model routing (R5): NULL for runs that did not go through the router/benchmark
                         ("initial_model", "TEXT"), ("final_model", "TEXT"), ("escalation_count", "INTEGER"),
                         ("retry_count", "INTEGER"), ("routing_strategy", "TEXT"))

LIST_COLUMNS = ("run_id, session_id, created_at, question_id, query, pipeline, agent, provider, model, mode,"
                " repetition, warmup, threshold, jev_mode, error, metrics_json")
FULL_EXTRA_COLUMNS = ", config_json, config_hash, sources_json, context, context_encoding, answer"


def _chunks(seq: list, n: int) -> Iterator[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class _AsyncWriter:
    """ANA-103 (EXPERIMENT, flag ANAMNESIA_DB_ASYNC_WRITES): one thread serialises `save_run` calls so
    request threads never wait on the SQLite write lock. `flush()` gives read-your-writes."""

    def __init__(self, db: "Database"):
        self._db = db
        self._q: queue.Queue = queue.Queue()
        self.errors: list[str] = []
        self._t = threading.Thread(target=self._loop, name="anamnesia-db-writer", daemon=True)
        self._t.start()

    def submit(self, row: dict, candidates: list[dict] | None) -> None:
        self._q.put((row, candidates))

    def _loop(self) -> None:
        while True:
            item = self._q.get()
            try:
                if item is None:
                    return
                self._db._save_run_sync(*item)
            except Exception as e:  # noqa: BLE001 - a failed telemetry write must not kill the writer
                self.errors.append(f"{type(e).__name__}: {e}")
                log.warning("escrita assíncrona falhou: %s", e)
            finally:
                self._q.task_done()

    def flush(self, timeout: float = 30.0) -> bool:
        if threading.current_thread() is self._t:
            return True
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.001)
        return not self._q.unfinished_tasks

    def stop(self) -> None:
        self._q.put(None)
        self._t.join(timeout=5)


class Database:
    def __init__(self, path: str | Path, compress_context: bool = False, *,
                 async_writes: bool | None = None, read_connection: bool | None = None):
        self.path = str(path)
        # Whether NEW rows get their `context` column zlib-compressed (base64-encoded text, so the
        # column stays TEXT). Reading never depends on this flag: `context_encoding` on each row
        # says how that row was written, so toggling this setting is always retrocompatible.
        self.compress_context = compress_context
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Wakes SSE streams the instant a run is inserted (no polling latency); see wait_new_run().
        self._run_cv = threading.Condition()
        self._run_seq = 0
        self.conn = sqlite3.connect(self.path, uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")           # ANA-060
        try:
            # ANA-061/096: the ONE migration runner (user_version, backup-before-migrate, refuse newer).
            self.migration_report = run_migrations(self.conn, BENCHMARK_MIGRATIONS, path=self.path,
                                                   label="benchmark.db")
        except BaseException:
            self.conn.close()
            raise
        self.conn.execute("PRAGMA journal_mode=WAL")
        # ANA-060: WAL + synchronous=NORMAL cannot corrupt the file; at worst the last commits are lost on
        # an OS crash/power cut (benchmark telemetry, not a source of truth). Saves an fsync per commit.
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA wal_autocheckpoint=1000")
        # ANA-103 / ANA-104 EXPERIMENTS: both OFF by default (flags); see scripts/measure_db_experiments.py
        self._writer: _AsyncWriter | None = None
        if async_writes if async_writes is not None else _env_on("ANAMNESIA_DB_ASYNC_WRITES"):
            self._writer = _AsyncWriter(self)
        self._reader: sqlite3.Connection | None = None
        self._rlock = threading.Lock()
        if (read_connection if read_connection is not None else _env_on("ANAMNESIA_DB_READER")) \
                and self.path != ":memory:":
            self._reader = self._open_reader()
        self._auto_retention()

    def _open_reader(self) -> sqlite3.Connection:
        """ANA-104: second, read-only connection (WAL lets it read while the writer commits)."""
        uri = Path(self.path).resolve().as_uri() + "?mode=ro"
        c = sqlite3.connect(uri, uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=5000")
        return c

    def _auto_retention(self) -> None:
        """ANA-095: opt-in startup maintenance (env ANAMNESIA_DB_RETENTION_DAYS > 0); never raises."""
        try:
            from app.database.retention import startup_maintenance
            startup_maintenance(self)
        except Exception as e:  # noqa: BLE001 - maintenance must never block startup
            log.warning("retenção no startup falhou: %s", e)

    def close(self) -> None:
        self.flush()
        if self._writer is not None:
            self._writer.stop()
        for c in (self._reader, self.conn):
            if c is not None:
                try:
                    c.close()
                except sqlite3.Error:
                    pass

    def flush(self, timeout: float = 30.0) -> bool:
        """ANA-103: wait for queued async writes (no-op when the experiment is off)."""
        return self._writer.flush(timeout) if self._writer is not None else True

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """ANA-060: several statements, ONE commit (atomic: all-or-nothing). Holds the write lock."""
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def query(self, sql: str, args: tuple = ()) -> list[dict]:
        if self._writer is not None:
            self._writer.flush()              # read-your-writes while async writes are on
        if self._reader is not None and sql.lstrip().upper().startswith(("SELECT", "WITH")):
            with self._rlock:                 # ANA-104: reads never wait for the writer lock
                return [dict(r) for r in self._reader.execute(sql, args).fetchall()]
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    # sessions / runs ---------------------------------------------------------
    def create_session(self, session_id: str, kind: str, config: dict, notes: str = "") -> None:
        self._exec("INSERT OR IGNORE INTO sessions VALUES (?,?,?,?,?)",
                   (session_id, time.time(), kind, json.dumps(config, default=str), notes))

    def _dedup_config(self, row: dict[str, Any]) -> tuple[str, str] | None:
        """Replace `config_json` (near-identical across runs) with a hash into `configs` (§5.3).
        Returns (hash, json) still to be inserted into `configs` (done inside save_run's transaction)."""
        cfg = row.get("config_json")
        if cfg is None:
            row["config_hash"] = None
            return None
        cfg_str = cfg if isinstance(cfg, str) else json.dumps(cfg, default=str, ensure_ascii=False)
        digest = hashlib.sha256(cfg_str.encode("utf-8")).hexdigest()
        row["config_hash"] = digest
        row["config_json"] = None
        return digest, cfg_str

    def _maybe_compress_context(self, row: dict[str, Any]) -> None:
        ctx = row.get("context")
        if self.compress_context and isinstance(ctx, str) and ctx:
            row["context"] = base64.b64encode(zlib.compress(ctx.encode("utf-8"), 6)).decode("ascii")
            row["context_encoding"] = "zlib+b64"
        else:
            row.setdefault("context_encoding", None)

    @staticmethod
    def _fill_ledger_fields(row: dict[str, Any]) -> None:
        """Derive project / terminal_session_id / cost_origin when the caller did not set them."""
        import os

        from app.services.costs import cost_origin_for, project_from_scope
        m = row.get("metrics_json")
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except ValueError:
                m = None
        m = m if isinstance(m, dict) else {}
        if row.get("project") is None:
            row["project"] = project_from_scope(m.get("scope"))
        if row.get("terminal_session_id") is None:
            row["terminal_session_id"] = os.environ.get("MG_TERMINAL_SESSION") or None
        if row.get("cost_origin") is None:
            row["cost_origin"] = cost_origin_for(m, row.get("pipeline"))
        if _env_on("ANAMNESIA_COST_SCHEMA") and "cost_schema" not in m and m:
            # ANA-175: every saved run carries the typed parcels; unmeasured parcels stay 'unavailable' (never 0).
            from app.services.cost_ledger import attach_cost_schema, build_cost_schema
            row["metrics_json"] = attach_cost_schema(m, build_cost_schema())

    def save_run(self, row: dict[str, Any], candidates: list[dict] | None = None) -> None:
        if self._writer is not None:                       # ANA-103 (experiment, flag off by default)
            self._writer.submit(dict(row), list(candidates or []))
            return
        self._save_run_sync(row, candidates)

    def _save_run_sync(self, row: dict[str, Any], candidates: list[dict] | None = None) -> None:
        """ANA-060: config + run + all candidates in ONE transaction (one commit/fsync, atomic)."""
        row = dict(row)
        self._fill_ledger_fields(row)
        cfg_pending = self._dedup_config(row)
        if _env_on("ANAMNESIA_METRICS_TRIM"):          # ANA-133 (opt-in): drop duplicated nested blocks
            from app.database.retention import trim_metrics
            mj = row.get("metrics_json")
            if isinstance(mj, str):
                try:
                    mj = json.loads(mj)
                except ValueError:
                    mj = None
            if isinstance(mj, dict):
                row["metrics_json"] = trim_metrics(mj)
        if row.get("context") and not row.get("context_sha256"):
            # ANAM-006: o hash do contexto entregue é sempre persistido (sobrevive ao expurgo do texto).
            row["context_sha256"] = hashlib.sha256(str(row["context"]).encode("utf-8")).hexdigest()
        if os.environ.get("ANAMNESIA_METRICS_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}:
            # ANA-041 / P-01: keep hash + sources, never the delivered context text.
            row["context"] = None
        self._maybe_compress_context(row)
        cols = ["run_id", "session_id", "created_at", "question_id", "query", "pipeline", "agent", "provider",
                "model", "mode", "repetition", "warmup", "order_index", "threshold", "jev_mode", "jev_model",
                "cache_enabled", "config_json", "config_hash", "metrics_json", "sources_json",
                "context", "context_encoding", "answer", "error",
                "project", "terminal_session_id", "cost_origin",
                "initial_model", "final_model", "escalation_count", "retry_count", "routing_strategy",
                "context_sha256"]
        vals = []
        for c in cols:
            v = row.get(c)
            if c.endswith("_json") and v is not None and not isinstance(v, str):
                v = json.dumps(v, default=str, ensure_ascii=False)
            vals.append(v)
        cand_rows = [(row["run_id"], cd["candidate_id"], cd["source_file"], cd["section"], cd["score"],
                      cd.get("relevance"), cd.get("injection"), cd.get("decision"), cd.get("token_estimate"))
                     for cd in candidates or []]
        with self._tx() as cx:
            if cfg_pending:
                cx.execute("INSERT OR IGNORE INTO configs (hash, json) VALUES (?,?)", cfg_pending)
            cx.execute(f"INSERT OR REPLACE INTO runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       tuple(vals))
            if cand_rows:
                cx.executemany("INSERT INTO candidates VALUES (?,?,?,?,?,?,?,?,?)", cand_rows)
        self._publish_run()

    def _publish_run(self) -> None:
        with self._run_cv:
            self._run_seq += 1
            self._run_cv.notify_all()

    @property
    def run_seq(self) -> int:
        return self._run_seq

    def wait_new_run(self, seen_seq: int, timeout: float) -> int:
        """Block until a run was saved after `seen_seq` (or `timeout` s). Returns the current sequence."""
        with self._run_cv:
            if self._run_seq == seen_seq and timeout > 0:
                self._run_cv.wait(timeout)
            return self._run_seq

    # key/value settings (persisted app settings; JSON values) ------------------
    def get_kv(self, key: str) -> Any | None:
        rows = self.query("SELECT value FROM kv WHERE key=?", (key,))
        if not rows:
            return None
        try:
            return json.loads(rows[0]["value"])
        except (TypeError, ValueError):
            return None

    def set_kv(self, key: str, value: Any) -> None:
        self._exec("INSERT OR REPLACE INTO kv (key, value, updated_at) VALUES (?,?,?)",
                   (key, json.dumps(value, ensure_ascii=False, default=str), time.time()))

    def run_evidence(self, run_id: str) -> list[dict]:
        """ANA-153: the notes a run delivered and why -- ONE SQL query (json_each over sources_json)."""
        return self.query(
            "SELECT json_extract(j.value,'$.file') AS file, json_extract(j.value,'$.section') AS section,"
            " json_extract(j.value,'$.score') AS score, json_extract(j.value,'$.decision') AS decision,"
            " json_extract(j.value,'$.tokens') AS tokens, json_extract(j.value,'$.why') AS why,"
            " r.query AS query, r.pipeline AS pipeline, r.created_at AS created_at"
            " FROM runs r, json_each(r.sources_json) j WHERE r.run_id=? ORDER BY j.key", (run_id,))

    def runs_for_note(self, file: str, limit: int = 20) -> list[dict]:
        """ANA-153 (reverse chain): which runs/queries retrieved this note."""
        return self.query(
            "SELECT r.run_id AS run_id, r.query AS query, r.pipeline AS pipeline, r.created_at AS created_at,"
            " json_extract(j.value,'$.why') AS why FROM runs r, json_each(r.sources_json) j"
            " WHERE json_extract(j.value,'$.file')=? ORDER BY r.created_at DESC LIMIT ?", (file, max(1, min(int(limit), 200))))

    def last_search_run(self) -> dict | None:
        """Newest ad-hoc (interactive/MCP/REST) search run, with decoded sources and candidates."""
        rows = self.query("SELECT run_id FROM runs WHERE session_id='adhoc' AND COALESCE(warmup,0)=0"
                          " ORDER BY created_at DESC, rowid DESC LIMIT 1")
        return self.get_run(rows[0]["run_id"]) if rows else None

    def benchmark_rows(self, session_id: str | None = None, since: float | None = None,
                       until: float | None = None, include_warmup: bool = False) -> list[dict]:
        """Runs reduced to (pipeline, metrics) for server-side aggregation; no heavy columns."""
        where, args = [], []
        if not include_warmup:
            where.append("COALESCE(warmup,0)=0 AND COALESCE(mode,'')<>'warmup'")
        if session_id:
            where.append("session_id=?"); args.append(session_id)
        if since is not None:
            where.append("created_at>=?"); args.append(since)
        if until is not None:
            where.append("created_at<=?"); args.append(until)
        sql = "SELECT run_id, pipeline, created_at, error, jev_model, metrics_json FROM runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return self.query(sql, tuple(args))

    def evaluation_scores(self, session_id: str | None = None, since: float | None = None,
                          until: float | None = None) -> list[dict]:
        where, args = [], []
        if session_id:
            where.append("r.session_id=?"); args.append(session_id)
        if since is not None:
            where.append("r.created_at>=?"); args.append(since)
        if until is not None:
            where.append("r.created_at<=?"); args.append(until)
        sql = ("SELECT COALESCE(e.pipeline, r.pipeline) AS pipeline, COUNT(*) AS n,"
               " AVG(e.accuracy) AS accuracy, AVG(e.completeness) AS completeness,"
               " AVG(e.groundedness) AS groundedness, AVG(e.citation_quality) AS citation_quality"
               " FROM evaluations e JOIN runs r ON r.run_id=e.run_id")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " GROUP BY COALESCE(e.pipeline, r.pipeline)"
        return self.query(sql, tuple(args))

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
                if k == "metrics_json" and isinstance(r["metrics"], dict) and "_trimmed" in r["metrics"]:
                    from app.database.retention import expand_metrics     # ANA-133
                    expand_metrics(r["metrics"])
            else:
                r.pop(k, None)
        return r

    def purge_context(self, older_than_days: float) -> int:
        """ANA-041: blank the stored `context` of runs older than N days (hash/sources/metrics stay).
        Returns the number of rows touched. N <= 0 is a no-op."""
        if not older_than_days or older_than_days <= 0:
            return 0
        cutoff = time.time() - older_than_days * 86400
        cur = self._exec(
            "UPDATE runs SET context = NULL, context_encoding = NULL WHERE context IS NOT NULL AND created_at < ?",
            (cutoff,))
        return cur.rowcount or 0

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
    # tabelas com run_id que devem acompanhar a run no expurgo (ANAM-006: sem órfãos)
    _RUN_CHILD_TABLES = ("candidates", "routing_decisions", "verification_results", "evaluations",
                         "false_negatives", "retrieval_labels")

    def prune(self, keep_days: int, keep_sessions: list[str] | None = None, dry_run: bool = False) -> dict:
        """Delete runs (and every dependent row) older than `keep_days`. Runs whose session_id is in
        `keep_sessions` are never deleted, regardless of age. ANAM-006: cascade in ONE transaction
        (candidates, routing_decisions, verification_results, evaluations, false_negatives,
        retrieval_labels) so no orphans are left behind."""
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
        with self._tx() as cx:
            for chunk in _chunks(run_ids, 500):
                ph = ",".join("?" * len(chunk))
                for t in self._RUN_CHILD_TABLES:
                    cx.execute(f"DELETE FROM {t} WHERE run_id IN ({ph})", tuple(chunk))
                cx.execute(f"DELETE FROM runs WHERE run_id IN ({ph})", tuple(chunk))
        return {"deleted": len(run_ids), "cutoff": cutoff, "dry_run": False}

    def schema_version(self) -> int:
        return int(self.query("PRAGMA user_version")[0]["user_version"])

    def backup_before_prune(self) -> str | None:
        """ANAM-006: consistent copy next to the DB as ``<db>.bak-v<user_version>`` (never overwrites).
        Restore = close the DB and copy the .bak over it. None for :memory:."""
        if self.path in ("", ":memory:") or not Path(self.path).exists():
            return None
        from app.database.migrations import backup_database
        version = self.schema_version()          # fora do lock (query() o adquire; não é reentrante)
        with self._lock:
            if self.conn.in_transaction:
                self.conn.commit()
            return str(backup_database(self.conn, self.path, version))

    @staticmethod
    def runs_text_retention_days() -> float:
        """ANAM-006 / decisão D-4 (pendente, REVISÁVEL): dias de retenção do texto de runs
        (query/context/answer). Env ANAMNESIA_RUNS_TEXT_RETENTION_DAYS; default 30; 0 desliga."""
        try:
            return float(os.environ.get("ANAMNESIA_RUNS_TEXT_RETENTION_DAYS", "").strip() or 30)
        except ValueError:
            return 30.0

    def purge_run_text(self, older_than_days: float | None = None, keep_sessions: list[str] | None = None,
                       dry_run: bool = False) -> dict:
        """ANAM-006: blank query/context/answer of runs older than N days (default: env retention).
        Run rows, metrics, sources and cost history stay; ``context_sha256`` is backfilled from the
        text BEFORE it is wiped, so the hash survives. N <= 0 is a no-op."""
        days = self.runs_text_retention_days() if older_than_days is None else older_than_days
        if not days or days <= 0:
            return {"purged": 0, "days": days, "dry_run": dry_run}
        cutoff = time.time() - days * 86400
        keep = [s for s in (keep_sessions or []) if s]
        where = ("created_at < ? AND (query IS NOT NULL OR context IS NOT NULL OR answer IS NOT NULL)")
        args: list[Any] = [cutoff]
        if keep:
            where += f" AND session_id NOT IN ({','.join('?' * len(keep))})"
            args += keep
        if dry_run:
            n = self.query(f"SELECT COUNT(*) n FROM runs WHERE {where}", tuple(args))[0]["n"]
            return {"would_purge": n, "days": days, "cutoff": cutoff, "dry_run": True}
        hashed = 0
        rows = self.query(f"SELECT run_id, context, context_encoding FROM runs WHERE {where}"
                          " AND context IS NOT NULL AND context_sha256 IS NULL", tuple(args))
        with self._tx() as cx:
            for r in rows:
                ctx = r["context"]
                if r["context_encoding"] == "zlib+b64":
                    ctx = zlib.decompress(base64.b64decode(ctx)).decode("utf-8")
                cx.execute("UPDATE runs SET context_sha256=? WHERE run_id=?",
                           (hashlib.sha256(str(ctx).encode("utf-8")).hexdigest(), r["run_id"]))
                hashed += 1
            cur = cx.execute(
                f"UPDATE runs SET query=NULL, context=NULL, context_encoding=NULL, answer=NULL WHERE {where}",
                tuple(args))
            purged = cur.rowcount or 0
        return {"purged": purged, "hashes_backfilled": hashed, "days": days, "cutoff": cutoff, "dry_run": False}

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

    # opt-in retention (T0.4) --------------------------------------------------
    HEAVY_RUN_COLUMNS = ("context", "answer", "sources_json")

    def _file_bytes(self) -> int:
        total = 0
        for suffix in ("", "-wal"):
            try:
                total += Path(self.path + suffix).stat().st_size
            except OSError:
                pass
        return total

    def _retention_stats(self, cutoff: float) -> dict:
        heavy_len = " + ".join(f"COALESCE(LENGTH({c}),0)" for c in self.HEAVY_RUN_COLUMNS)
        heavy_any = " OR ".join(f"{c} IS NOT NULL" for c in self.HEAVY_RUN_COLUMNS)
        r = self.query(f"SELECT COUNT(*) AS n, COALESCE(SUM({heavy_len}),0) AS b FROM runs"
                       f" WHERE created_at < ? AND ({heavy_any})", (cutoff,))[0]
        c = self.query("SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(key)+LENGTH(value)),0) AS b"
                       " FROM jev_cache WHERE created_at < ?", (cutoff,))[0]
        o = self.query("SELECT COUNT(*) AS n FROM candidates WHERE run_id NOT IN (SELECT run_id FROM runs)")[0]
        return {"runs_heavy_rows": r["n"], "runs_heavy_bytes": r["b"],
                "jev_cache_rows": c["n"], "jev_cache_bytes": c["b"], "orphan_candidates": o["n"]}

    def maintenance(self, older_than_days: int, apply: bool = False, vacuum: bool = False) -> dict:
        """Opt-in retention. Default is a dry run that only REPORTS. With apply=True it:
          * sets context/answer/sources_json to NULL on runs older than `older_than_days`
            (ids, metrics_json, config and every other column are kept, so cost history survives);
          * deletes jev_cache entries older than the same cutoff;
          * deletes candidates whose run no longer exists.
        VACUUM only runs with apply=True and vacuum=True. Idempotent. Never called automatically."""
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")
        cutoff = time.time() - older_than_days * 86400
        size_before = self._file_bytes()
        found = self._retention_stats(cutoff)
        result: dict[str, Any] = {"dry_run": not apply, "cutoff": cutoff, "older_than_days": older_than_days,
                                  "found": found, "size_before": size_before, "vacuumed": False}
        if apply:
            heavy_any = " OR ".join(f"{c} IS NOT NULL" for c in self.HEAVY_RUN_COLUMNS)
            nulls = ", ".join(f"{c}=NULL" for c in self.HEAVY_RUN_COLUMNS)
            runs = self._exec(f"UPDATE runs SET {nulls} WHERE created_at < ? AND ({heavy_any})", (cutoff,)).rowcount
            cache = self._exec("DELETE FROM jev_cache WHERE created_at < ?", (cutoff,)).rowcount
            orph = self._exec("DELETE FROM candidates WHERE run_id NOT IN (SELECT run_id FROM runs)").rowcount
            result["applied"] = {"runs_stripped": runs, "jev_cache_deleted": cache, "orphan_candidates_deleted": orph}
            if vacuum:
                self.vacuum()
                with self._lock:
                    self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
                result["vacuumed"] = True
        result["size_after"] = self._file_bytes() if apply else size_before
        return result

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

    def purge_stale(self, current_identity: str | None = None, ttl_days: float | None = None,
                    max_rows: int | None = None, apply: bool = True) -> dict:
        """ANA-099: jev_cache governance. Removes (a) rows whose stored `identity` digest differs from the
        CURRENT one (unreachable under the current version vector), (b) rows older than `ttl_days`
        (by the row's created_at), (c) the oldest rows beyond `max_rows`. Rows without an identity
        (legacy single-layer keys) are only subject to TTL / cap. apply=False only counts."""
        ids: set[str] = set()
        for label, sql, args in (
            ("stale_identity", "SELECT key FROM jev_cache WHERE json_extract(value,'$.identity') IS NOT NULL"
                               " AND json_extract(value,'$.identity') <> ?", (current_identity,)),
            ("expired", "SELECT key FROM jev_cache WHERE created_at < ?",
             (time.time() - (ttl_days or 0) * 86400,)),
        ):
            if label == "stale_identity" and not current_identity:
                continue
            if label == "expired" and not ttl_days:
                continue
            ids |= {r["key"] for r in self.query(sql, args)}
        over = 0
        if max_rows is not None and max_rows >= 0:
            total = self.query("SELECT COUNT(*) n FROM jev_cache")[0]["n"] - len(ids)
            over = max(0, total - max_rows)
            if over:
                ids |= {r["key"] for r in self.query(
                    "SELECT key FROM jev_cache ORDER BY created_at ASC LIMIT ?", (len(ids) + over,))}
        deleted = 0
        if apply and ids:
            with self._tx() as cx:
                for chunk in _chunks(sorted(ids), 500):
                    cx.execute(f"DELETE FROM jev_cache WHERE key IN ({','.join('?' * len(chunk))})", chunk)
                    deleted += len(chunk)
        return {"candidates": len(ids), "deleted": deleted, "over_cap": over, "dry_run": not apply}

    def cache_stats(self) -> dict:
        r = self.query("SELECT COUNT(*) n, COALESCE(SUM(LENGTH(key)+LENGTH(value)),0) b,"
                       " MIN(created_at) oldest FROM jev_cache")[0]
        return {"rows": r["n"], "bytes": r["b"], "oldest": r["oldest"]}

    # costs ledger read helpers (additive) ---------------------------------------
    COST_COLUMNS = ("rowid AS _rowid, run_id, created_at, project, terminal_session_id, cost_origin, agent, "
                    "provider, model, mode, pipeline, jev_model, query, error, metrics_json")

    def cost_rows(self, since: float | None = None, project: str | None = None,
                  limit: int | None = None, before: tuple[float, str] | None = None,
                  ascending: bool = False) -> list[dict]:
        """Runs for the ledger, newest first. `before` = keyset cursor (created_at, run_id)."""
        where, args = [], []
        if since is not None:
            where.append("created_at >= ?"); args.append(since)
        if project:
            where.append("project = ?"); args.append(project)
        if before is not None:
            where.append("(created_at < ? OR (created_at = ? AND run_id < ?))")
            args += [before[0], before[0], before[1]]
        sql = f"SELECT {self.COST_COLUMNS} FROM runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at ASC, run_id ASC" if ascending else " ORDER BY created_at DESC, run_id DESC"
        if limit is not None:
            sql += " LIMIT ?"; args.append(int(limit))
        return self.query(sql, tuple(args))

    def cost_rows_after_rowid(self, rowid: int) -> list[dict]:
        return self.query(f"SELECT {self.COST_COLUMNS} FROM runs WHERE rowid > ? ORDER BY rowid ASC", (rowid,))

    def max_run_rowid(self) -> int:
        return int(self.query("SELECT COALESCE(MAX(rowid), 0) AS m FROM runs")[0]["m"])

    # model routing helpers (R5, additive) ---------------------------------------
    def set_run_routing(self, run_id: str, initial_model: str | None, final_model: str | None,
                        escalation_count: int | None, retry_count: int | None,
                        routing_strategy: str | None) -> None:
        """Routing columns of an existing run (save_run's INSERT OR REPLACE resets them: call this after)."""
        self._exec("UPDATE runs SET initial_model=?, final_model=?, escalation_count=?, retry_count=?,"
                   " routing_strategy=? WHERE run_id=?",
                   (initial_model, final_model, escalation_count, retry_count, routing_strategy, run_id))

    def insert_routing_decision(self, run_id: str, d: dict) -> None:
        """One decision per run (replaced when called again). Unmeasured fields stay NULL."""
        codes = d.get("reason_codes")
        if codes is not None and not isinstance(codes, str):
            codes = json.dumps(list(codes), ensure_ascii=False)
        self._exec("DELETE FROM routing_decisions WHERE run_id=?", (run_id,))
        self._exec("INSERT INTO routing_decisions (run_id, policy_version, registry_version, complexity, risk, tier,"
                   " model, effort, verify, reason_codes, router_tokens, router_cost, latency_ms)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, d.get("policy_version"), d.get("registry_version"), d.get("complexity"), d.get("risk"),
                    d.get("tier"), d.get("model"), d.get("effort"), d.get("verify"), codes,
                    d.get("router_tokens"), d.get("router_cost"), d.get("latency_ms")))

    def insert_verification_result(self, run_id: str, attempt: int, level: str | None, passed: bool | None,
                                   tokens: int | None = None, cost: float | None = None,
                                   failure_code: str | None = None) -> None:
        self._exec("INSERT INTO verification_results (run_id, attempt, level, passed, tokens, cost, failure_code)"
                   " VALUES (?,?,?,?,?,?,?)",
                   (run_id, attempt, level, None if passed is None else int(bool(passed)), tokens, cost, failure_code))

    def routing_decision(self, run_id: str) -> dict | None:
        rows = self.query("SELECT * FROM routing_decisions WHERE run_id=?", (run_id,))
        if not rows:
            return None
        r = rows[0]
        try:
            r["reason_codes"] = json.loads(r["reason_codes"]) if r.get("reason_codes") else []
        except ValueError:
            pass
        return r

    def verification_results(self, run_id: str) -> list[dict]:
        rows = self.query("SELECT * FROM verification_results WHERE run_id=? ORDER BY attempt", (run_id,))
        for r in rows:
            if r["passed"] is not None:
                r["passed"] = bool(r["passed"])
        return rows

    def routing_runs(self) -> list[dict]:
        """Runs produced by the routing benchmark/router (routing_strategy IS NOT NULL), oldest first."""
        return self.query("SELECT run_id, session_id, created_at, question_id, model, initial_model, final_model,"
                          " escalation_count, retry_count, routing_strategy, metrics_json FROM runs"
                          " WHERE routing_strategy IS NOT NULL ORDER BY created_at ASC, run_id ASC")

    def get_budgets(self) -> dict[str, float | None]:
        return {r["period"]: r["ceiling_usd"] for r in self.query("SELECT period, ceiling_usd FROM budgets")}

    def set_budget(self, period: str, ceiling_usd: float | None) -> None:
        if ceiling_usd is None:
            self._exec("DELETE FROM budgets WHERE period=?", (period,))
        else:
            self._exec("INSERT OR REPLACE INTO budgets (period, ceiling_usd, updated_at) VALUES (?,?,?)",
                       (period, float(ceiling_usd), time.time()))
