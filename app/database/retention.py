"""Automatic, budgeted retention for benchmark.db (ANA-095) + jev_cache governance (ANA-099).

``startup_maintenance(db)`` is called from ``Database.__init__`` and is a NO-OP unless explicitly
enabled (opt-in; the default keeps every byte, exactly like before):

  ANAMNESIA_DB_RETENTION_DAYS   N>0  -> strip heavy columns of runs older than N days, drop old
                                        jev_cache rows, drop orphan candidates (``Database.maintenance``)
  ANAMNESIA_JEV_CACHE_TTL_DAYS  N>0  -> TTL for jev_cache (default: same as retention days)
  ANAMNESIA_JEV_CACHE_MAX_ROWS  N>0  -> keep at most N newest jev_cache rows
  ANAMNESIA_DB_VACUUM_DAYS      N>0  -> VACUUM when the last one is older than N days (30 = monthly),
                                        remembered in kv['last_vacuum']
  ANAMNESIA_DB_MAX_MB           N>0  -> log a WARNING when the file exceeds N MB (default 512; alert only)

Runs are never deleted: ids, metrics_json and config stay, so the cost history survives.
"""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("anamnesia.retention")
DAY = 86400


def _num(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def footprint(db) -> dict:
    """Where the bytes are (payload bytes per column/table), file size and growth per 1000 runs.
    Read-only; run it against a COPY of benchmark.db for big files."""
    def s(sql: str) -> int:
        return int(db.query(sql)[0]["b"] or 0)

    runs = db.query("SELECT COUNT(*) n FROM runs")[0]["n"]
    out = {
        "file_bytes": db._file_bytes(), "runs": runs,
        "page_size": db.query("PRAGMA page_size")[0]["page_size"],
        "free_pages": db.query("PRAGMA freelist_count")[0]["freelist_count"],
        "bytes": {
            "runs.metrics_json": s("SELECT SUM(LENGTH(metrics_json)) b FROM runs"),
            "runs.context": s("SELECT SUM(LENGTH(context)) b FROM runs"),
            "runs.config_json": s("SELECT SUM(LENGTH(config_json)) b FROM runs"),
            "runs.sources_json": s("SELECT SUM(LENGTH(sources_json)) b FROM runs"),
            "runs.answer": s("SELECT SUM(LENGTH(answer)) b FROM runs"),
            "runs.query": s("SELECT SUM(LENGTH(query)) b FROM runs"),
            "jev_cache": s("SELECT SUM(LENGTH(key)+LENGTH(value)) b FROM jev_cache"),
            "candidates(~)": s("SELECT SUM(LENGTH(run_id)+LENGTH(candidate_id)+LENGTH(source_file)"
                               "+LENGTH(section)+24) b FROM candidates"),
        },
    }
    out["bytes_per_run"] = round(out["file_bytes"] / runs) if runs else None
    out["mb_per_1000_runs"] = round(out["file_bytes"] / 1048576 / runs * 1000, 2) if runs else None
    return out


def compress_old_contexts(db, older_than_days: float, apply: bool = False) -> dict:
    """Compress (zlib+b64) the plain-text `context` of runs older than N days. Reading is unaffected:
    ``Database._decode`` already honours ``context_encoding`` per row."""
    import base64
    import zlib
    cutoff = time.time() - older_than_days * DAY
    rows = db.query("SELECT run_id, context FROM runs WHERE context IS NOT NULL AND context<>''"
                    " AND COALESCE(context_encoding,'')='' AND created_at<?", (cutoff,))
    before = sum(len(r["context"]) for r in rows)
    after = 0
    batch = []
    for r in rows:
        enc = base64.b64encode(zlib.compress(r["context"].encode("utf-8"), 6)).decode("ascii")
        if len(enc) < len(r["context"]):
            after += len(enc)
            batch.append((enc, r["run_id"]))
        else:
            after += len(r["context"])
    if apply and batch:
        with db._tx() as cx:
            cx.executemany("UPDATE runs SET context=?, context_encoding='zlib+b64' WHERE run_id=?", batch)
    return {"rows": len(rows), "compressed": len(batch) if apply else 0, "bytes_before": before,
            "bytes_after": after, "dry_run": not apply}


def startup_maintenance(db) -> dict | None:
    days = _num("ANAMNESIA_DB_RETENTION_DAYS")
    vac_days = _num("ANAMNESIA_DB_VACUUM_DAYS")
    max_mb = _num("ANAMNESIA_DB_MAX_MB", 512.0)
    report: dict = {}
    ttl = _num("ANAMNESIA_JEV_CACHE_TTL_DAYS", days)
    cap = int(_num("ANAMNESIA_JEV_CACHE_MAX_ROWS"))
    if days > 0:
        report["maintenance"] = db.maintenance(days, apply=True)
    if (ttl > 0 or cap > 0) and not (days > 0 and ttl == days and not cap):
        report["jev_cache"] = db.purge_stale(ttl_days=ttl or None, max_rows=cap or None)
    if vac_days > 0:
        last = db.get_kv("last_vacuum") or 0
        if time.time() - float(last) >= vac_days * DAY:
            db.vacuum()
            db.set_kv("last_vacuum", time.time())
            report["vacuumed"] = True
    size = db._file_bytes()
    if max_mb > 0 and size > max_mb * 1048576:
        log.warning("benchmark.db tem %.0f MB (> ANAMNESIA_DB_MAX_MB=%.0f): rode `db-maintenance --apply --vacuum`",
                    size / 1048576, max_mb)
        report["size_alert_mb"] = round(size / 1048576, 1)
    return report or None


# ---- ANA-133: leaner metrics_json (opt-in, ANAMNESIA_METRICS_TRIM=1) ------------------------------
# Measured on a copy of benchmark.db (6051 runs): `jev.cache_layers` / `jev.opt_flags` repeat the
# top-level blocks of the same name byte for byte -> 1.52 MB = 6.25% of metrics_json (1.3% of the file).
# The duplicate is dropped on write and re-expanded by `Database._decode`, marked by `_trimmed`.
_DUP_KEYS = ("cache_layers", "opt_flags")


def trim_metrics(m: dict) -> dict:
    """Return a copy of `m` without nested `jev.<k>` blocks identical to top-level `<k>` (lossless)."""
    j = m.get("jev")
    if not isinstance(j, dict):
        return m
    dup = [k for k in _DUP_KEYS if k in j and k in m and j[k] == m[k]]
    if not dup:
        return m
    out = dict(m)
    out["jev"] = {k: v for k, v in j.items() if k not in dup}
    out["_trimmed"] = dup
    return out


def expand_metrics(m: dict) -> dict:
    """Inverse of `trim_metrics` (no-op for untrimmed metrics)."""
    dup = m.pop("_trimmed", None)
    if dup and isinstance(m.get("jev"), dict):
        for k in dup:
            if k in m:
                m["jev"][k] = m[k]
    return m
