"""ANA-175 + ANA-188: complete per-run cost schema and idempotent backfill of `cost_origin`/`project`.

ANA-175 -- every run can carry, inside `metrics_json["cost_schema"]` (NO new column), six token parcels, each
labelled with its own origin:  embedding_tokens, rewrite_tokens, router_tokens, verify_tokens, retry_tokens,
cache_saved_tokens. `cache_saved_tokens` is a SAVING (tokens NOT sent thanks to cache), so it is reported but is
never part of the spent total. Invariant (checked, not assumed):
    total_tokens_spent == sum(spent parcels)    whenever every spent parcel is known.
A parcel that was not measured is None/'unavailable' and makes the sum unknown (never 0). A parcel that is a
true zero (deterministic code, no LLM call) is 0 with origin 'no_llm'.

ANA-188 -- `backfill_cost_origin` fills `runs.cost_origin` (via services.costs.cost_origin_for) and `runs.project`
(via project_from_scope) ONLY where they are NULL, in batches, with dry-run, writing the previous values into
`cost_backfill_log` so that `rollback_backfill` restores them exactly. Idempotent: a second pass touches 0 rows.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from app.services.costs import cost_origin_for, project_from_scope

SPENT_PARCELS = ("embedding_tokens", "rewrite_tokens", "router_tokens", "verify_tokens", "retry_tokens")
SAVED_PARCELS = ("cache_saved_tokens",)
ALL_PARCELS = SPENT_PARCELS + SAVED_PARCELS
ORIGINS = ("measured", "estimated", "no_llm", "not_applicable", "unavailable")
SCHEMA_KEY = "cost_schema"
LOG_TABLE = "cost_backfill_log"


def parcel(value: int | None, origin: str | None = None) -> dict:
    """Typed parcel. None => origin 'unavailable' (forced). 0 needs an explicit non-'unavailable' origin."""
    if value is None:
        return {"value": None, "origin": "unavailable"}
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"token parcel must be a non-negative number, got {value!r}")
    o = origin or "estimated"
    if o not in ORIGINS or o == "unavailable":
        raise ValueError(f"bad origin {o!r} for a known value")
    return {"value": int(value), "origin": o}


def build_cost_schema(**parcels: tuple[int | None, str | None] | int | None) -> dict:
    """build_cost_schema(router_tokens=(0, 'no_llm'), verify_tokens=(0, 'no_llm'), embedding_tokens=(120, 'estimated')).
    Missing parcels are 'unavailable'. Returns {"parcels": {...}, "spent_total": {...}}."""
    unknown = set(parcels) - set(ALL_PARCELS)
    if unknown:
        raise ValueError(f"unknown parcels: {sorted(unknown)}")
    out: dict[str, dict] = {}
    for k in ALL_PARCELS:
        v = parcels.get(k)
        out[k] = parcel(*v) if isinstance(v, tuple) else parcel(v, None)
    return {"parcels": out, "spent_total": spent_total(out)}


def spent_total(parcels: dict) -> dict:
    """Sum of spent parcels; unknown if ANY is unknown. Origin = worst origin among the known ones."""
    vals = [parcels.get(k, {}).get("value") for k in SPENT_PARCELS]
    if any(v is None for v in vals):
        return {"value": None, "origin": "unavailable",
                "missing": [k for k, v in zip(SPENT_PARCELS, vals) if v is None]}
    origins = {parcels[k]["origin"] for k in SPENT_PARCELS}
    worst = "estimated" if "estimated" in origins else "measured"
    return {"value": int(sum(vals)), "origin": worst, "missing": []}


def attach_cost_schema(metrics: dict, schema: dict) -> dict:
    """Return a COPY of `metrics` with the schema under metrics['cost_schema'] (the input is not mutated)."""
    m = dict(metrics)
    m[SCHEMA_KEY] = schema
    return m


def check_invariant(metrics: dict) -> dict:
    """{"status": "ok"|"violation"|"unknown"|"no_schema", ...}. 'unknown' = a spent parcel is unavailable
    (nothing to assert); 'violation' = all known but total_tokens_spent != their sum."""
    sch = metrics.get(SCHEMA_KEY)
    if not isinstance(sch, dict) or "parcels" not in sch:
        return {"status": "no_schema"}
    tot = spent_total(sch["parcels"])
    if tot["value"] is None:
        return {"status": "unknown", "missing": tot["missing"]}
    declared = metrics.get("total_tokens_spent")
    if declared is None:
        return {"status": "unknown", "missing": ["total_tokens_spent"]}
    if declared != tot["value"]:
        return {"status": "violation", "declared": declared, "sum_of_parcels": tot["value"]}
    return {"status": "ok", "total": tot["value"]}


def schema_from_bench_record(rec: dict) -> dict:
    """Map a routing-benchmark record onto the schema. embedding/rewrite are not part of that benchmark
    (no retrieval step is measured there) => 'unavailable', never 0."""
    def ov(k):
        return rec.get(k)

    def origin_of(key):
        o = rec.get(key)
        return o if o in ORIGINS and o != "unavailable" else None

    return build_cost_schema(
        router_tokens=(ov("router_tokens"), origin_of("router_tokens_origin")) if ov("router_tokens") is not None else None,
        verify_tokens=(ov("verify_tokens"), origin_of("verify_tokens_origin")) if ov("verify_tokens") is not None else None,
        retry_tokens=(ov("retry_tokens"), "measured") if ov("retry_tokens") is not None else None)


# ------------------------------------------------------------------ ANA-188 backfill
def _ensure_log(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS {LOG_TABLE} (run_id TEXT PRIMARY KEY, prev_cost_origin TEXT,"
                 f" prev_project TEXT, new_cost_origin TEXT, new_project TEXT, applied_at REAL)")


def _metrics(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        m = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return {}
    return m if isinstance(m, dict) else {}


def plan_row(row: sqlite3.Row | tuple) -> tuple[str | None, str | None]:
    """(new_cost_origin, new_project) for a row (run_id, pipeline, metrics_json, cost_origin, project);
    None where nothing is to be written."""
    _rid, pipeline, mj, cost_origin, project = row
    m = _metrics(mj)
    new_co = cost_origin_for(m, pipeline) if cost_origin is None else None
    new_pr = project_from_scope(m.get("scope")) if project is None else None
    return new_co, new_pr


def backfill_cost_origin(conn: sqlite3.Connection, *, dry_run: bool = True, batch_size: int = 500) -> dict:
    """Fill NULL cost_origin / project of old runs. dry_run=True (default) changes NOTHING and reports counts.
    Does not commit: the caller (migration runner or script) owns the transaction."""
    import time
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    if not dry_run:
        _ensure_log(conn)
    rep = {"dry_run": dry_run, "scanned": 0, "cost_origin_filled": 0, "project_filled": 0, "rows_changed": 0,
           "cost_origin_null_before": conn.execute("SELECT COUNT(*) FROM runs WHERE cost_origin IS NULL").fetchone()[0],
           "project_null_before": conn.execute("SELECT COUNT(*) FROM runs WHERE project IS NULL").fetchone()[0]}
    last = ""
    while True:
        rows = conn.execute("SELECT run_id, pipeline, metrics_json, cost_origin, project FROM runs"
                            " WHERE (cost_origin IS NULL OR project IS NULL) AND run_id > ? ORDER BY run_id LIMIT ?",
                            (last, batch_size)).fetchall()
        if not rows:
            break
        for row in rows:
            rep["scanned"] += 1
            new_co, new_pr = plan_row(tuple(row))
            if new_co is None and new_pr is None:
                continue
            rep["rows_changed"] += 1
            rep["cost_origin_filled"] += new_co is not None
            rep["project_filled"] += new_pr is not None
            if not dry_run:
                conn.execute(f"INSERT OR IGNORE INTO {LOG_TABLE} VALUES (?,?,?,?,?,?)",
                             (row[0], row[3], row[4], new_co, new_pr, time.time()))
                conn.execute("UPDATE runs SET cost_origin = COALESCE(cost_origin, ?), project = COALESCE(project, ?)"
                             " WHERE run_id = ?", (new_co, new_pr, row[0]))
        last = rows[-1][0]
    rep["cost_origin_null_after"] = (rep["cost_origin_null_before"] if dry_run else
                                     conn.execute("SELECT COUNT(*) FROM runs WHERE cost_origin IS NULL").fetchone()[0])
    return rep


def rollback_backfill(conn: sqlite3.Connection) -> dict:
    """Restore the pre-backfill values recorded in cost_backfill_log (only where the value is still the one we
    wrote) and clear the log. No-op when the log does not exist."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (LOG_TABLE,)).fetchone() is None:
        return {"restored": 0}
    n = 0
    for rid, pco, ppr, nco, npr, _t in conn.execute(f"SELECT * FROM {LOG_TABLE}").fetchall():
        conn.execute("UPDATE runs SET cost_origin = CASE WHEN ? IS NOT NULL AND cost_origin = ? THEN ? ELSE cost_origin END,"
                     " project = CASE WHEN ? IS NOT NULL AND project = ? THEN ? ELSE project END WHERE run_id = ?",
                     (nco, nco, pco, npr, npr, ppr, rid))
        n += 1
    conn.execute(f"DELETE FROM {LOG_TABLE}")
    return {"restored": n}


def migration_apply(conn: sqlite3.Connection) -> None:
    """Body of benchmark migration v3. The runner already took a .bak copy and a transaction."""
    backfill_cost_origin(conn, dry_run=False)


def count_nulls(conn: sqlite3.Connection) -> dict:
    return {"cost_origin": conn.execute("SELECT COUNT(*) FROM runs WHERE cost_origin IS NULL").fetchone()[0],
            "project": conn.execute("SELECT COUNT(*) FROM runs WHERE project IS NULL").fetchone()[0]}


def iter_invariant_violations(rows: Iterable[dict]) -> list[str]:
    return [str(r.get("run_id")) for r in rows if check_invariant(_metrics(r.get("metrics_json")))["status"] == "violation"]
