"""SQLite persistence (§58). Database lives in the project (benchmark.db), never in the vault."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

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
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

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

    def save_run(self, row: dict[str, Any], candidates: list[dict] | None = None) -> None:
        cols = ["run_id", "session_id", "created_at", "question_id", "query", "pipeline", "agent", "provider",
                "model", "mode", "repetition", "warmup", "order_index", "threshold", "jev_mode", "jev_model",
                "cache_enabled", "config_json", "metrics_json", "sources_json", "context", "answer", "error"]
        vals = []
        for c in cols:
            v = row.get(c)
            if c.endswith("_json") and not isinstance(v, str):
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

    @staticmethod
    def _decode(r: dict) -> dict:
        for k in ("config_json", "metrics_json", "sources_json"):
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

    def list_runs(self, limit: int = 100, session_id: str | None = None) -> list[dict]:
        sql = ("SELECT run_id, session_id, created_at, question_id, query, pipeline, agent, provider, model, mode,"
               " repetition, warmup, threshold, jev_mode, error, metrics_json FROM runs")
        args: tuple = ()
        if session_id:
            sql += " WHERE session_id=?"
            args = (session_id,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        return [self._decode(r) for r in self.query(sql, args + (limit,))]

    def list_sessions(self, limit: int = 50) -> list[dict]:
        return self.query("SELECT s.*, (SELECT COUNT(*) FROM runs r WHERE r.session_id=s.session_id) AS runs"
                          " FROM sessions s ORDER BY created_at DESC LIMIT ?", (limit,))

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

    def false_negative_rate(self, pipeline: str = "graphify_jev") -> dict:
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
