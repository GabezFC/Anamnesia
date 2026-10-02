"""M1: histórico completo — sessões por última atividade, timeseries no servidor sem teto, timestamps."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.benchmark.timeseries import METRICS, build_series, build_timeseries, day_key, lttb, normalize_ts
from app.database.db import Database


def ts(y, mo, d, h=12, mi=0) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def _row(run_id, created_at, session_id="adhoc", pipeline="graphify_jev_opt", tokens=100, **over):
    base = {
        "run_id": run_id, "session_id": session_id, "created_at": created_at, "question_id": None,
        "query": "q", "pipeline": pipeline, "agent": "mcp", "provider": None, "model": None,
        "mode": "retrieval", "repetition": 0, "warmup": 0, "order_index": None, "threshold": None,
        "jev_mode": None, "jev_model": None, "cache_enabled": 0, "config_json": None,
        "metrics_json": {"total_tokens_spent": tokens, "context_tokens": 10}, "sources_json": [],
        "context": "c", "answer": None, "error": None,
    }
    base.update(over)
    return base


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "h.db"))
    yield d
    d.conn.close()


@pytest.fixture
def history_db(db):
    """'adhoc' registered on 24/09 (INSERT OR IGNORE keeps it), runs on 24/09, 28/09, 30/09, 01/10."""
    db.conn.execute("INSERT INTO sessions VALUES ('adhoc', ?, 'api', '{}', '')", (ts(2026, 9, 24, 9),))
    db.conn.execute("INSERT INTO sessions VALUES ('bench-27', ?, 'benchmark', '{}', '')", (ts(2026, 9, 27, 10),))
    db.conn.commit()
    db.create_session("adhoc", "api", {})  # must NOT move created_at
    for i, t in enumerate([ts(2026, 9, 24, 10), ts(2026, 9, 28), ts(2026, 9, 30), ts(2026, 10, 1)]):
        db.save_run(_row(f"a{i}", t, "adhoc", tokens=100 + i))
    for i in range(3):
        db.save_run(_row(f"b{i}", ts(2026, 9, 27, 10 + i), "bench-27", tokens=500))
    db.save_run(_row("orphan", ts(2026, 9, 29), "only-in-runs"))
    return db


# -- sessions ----------------------------------------------------------------------------------
def test_adhoc_session_sorted_first_with_last_run_at(history_db):
    rows = history_db.list_sessions()
    assert rows[0]["session_id"] == "adhoc"
    assert rows[0]["last_run_at"] == ts(2026, 10, 1)
    assert rows[0]["first_run_at"] == ts(2026, 9, 24, 10)
    assert rows[0]["created_at"] == ts(2026, 9, 24, 9)        # stored timestamp untouched
    assert rows[0]["runs"] == 4
    assert [r["session_id"] for r in rows] == ["adhoc", "only-in-runs", "bench-27"]


def test_sessions_only_in_runs_included_and_paginated(history_db):
    assert history_db.count_sessions() == 3
    page = history_db.list_sessions(limit=1, offset=1)
    assert [r["session_id"] for r in page] == ["only-in-runs"]
    assert page[0]["kind"] is None and page[0]["runs"] == 1


def test_session_without_runs_still_listed(db):
    db.create_session("empty", "benchmark", {})
    rows = db.list_sessions()
    assert rows[0]["session_id"] == "empty" and rows[0]["runs"] == 0 and rows[0]["last_run_at"] is None


def test_session_aggregate_uses_index(history_db):
    plan = " ".join(r["detail"] for r in history_db.query(
        "EXPLAIN QUERY PLAN SELECT session_id, MAX(created_at) FROM runs GROUP BY session_id"))
    assert "runs_session" in plan


# -- summary -----------------------------------------------------------------------------------
def test_history_summary(history_db):
    history_db.save_run(_row("ms", 1_790_000_000_000.0))            # milliseconds
    history_db.save_run(_row("nul", None))
    history_db.save_run(_row("txt", "not-a-number"))
    history_db.save_run(_row("w", ts(2026, 10, 1), warmup=1))
    s = history_db.history_summary()
    assert s["total_runs"] == 8 + 4 and s["invalid_timestamps"] == 3
    assert s["adhoc_runs"] == 4 + 4                                  # a0..a3 + ms, nul, txt, w
    assert s["warmup_runs"] == 1
    assert s["newest_run_at"] == ts(2026, 10, 1) and s["oldest_run_at"] == ts(2026, 9, 24, 10)
    assert s["total_sessions"] == 3
    assert s["runs_por_dia_utc"]["2026-10-01"] == 2
    assert s["runs_por_dia_utc"]["2026-09-27"] == 3
    assert sum(s["runs_por_dia"].values()) == 8 + 1


# -- normalisation -----------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    (1_790_000_000, 1_790_000_000.0), (1_790_000_000_000, 1_790_000_000.0), ("1790000000", 1_790_000_000.0),
    ("2026-10-01T12:00:00Z", ts(2026, 10, 1)), ("2026-10-01T12:00:00+00:00", ts(2026, 10, 1)),
    ("2026-10-01T09:00:00-03:00", ts(2026, 10, 1)), ("2026-10-01T12:00:00", ts(2026, 10, 1)),
    ("2026-10-01", ts(2026, 10, 1, 0)),
])
def test_normalize_ts_accepts(raw, expected):
    assert normalize_ts(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", float("nan"), float("inf"), -5, 0, True, [], {}])
def test_normalize_ts_rejects(raw):
    assert normalize_ts(raw) is None


# -- series ------------------------------------------------------------------------------------
def _rows(spec):
    return [{"run_id": f"r{i}", "session_id": s, "created_at": t, "pipeline": "p",
             "metrics_json": json.dumps({"total_tokens_spent": v})} for i, (t, s, v) in enumerate(spec)]


def test_series_sorted_asc_dedup_and_invalid_counted():
    rows = _rows([(ts(2026, 10, 1), "a", 3), (ts(2026, 9, 28), "a", 1), (ts(2026, 9, 29), "a", 2)])
    rows.append({**rows[0]})                                         # duplicate run_id
    rows.append({"run_id": "bad", "session_id": "a", "created_at": "garbage", "metrics_json": "{}"})
    rows.append({"run_id": "nul", "session_id": "a", "created_at": None, "metrics_json": "{}"})
    out = build_series(rows, "tokens", "run")
    xs = [p["x"] for p in out["points"]]
    assert xs == sorted(xs) and len(xs) == 3
    assert [p["y"] for p in out["points"]] == [1, 2, 3]
    assert out["invalid_dropped"] == 2 and out["total_runs_in_range"] == 3 and out["sampled"] is False


def test_series_accepts_ms_and_iso_timestamps():
    rows = _rows([(ts(2026, 9, 28) * 1000, "a", 1), ("2026-09-29T12:00:00Z", "a", 2), (ts(2026, 9, 30), "a", 3)])
    out = build_series(rows, "tokens", "run")
    assert [p["x"] for p in out["points"]] == [ts(2026, 9, 28), ts(2026, 9, 29), ts(2026, 9, 30)]
    assert out["invalid_dropped"] == 0


def test_day_aggregation_median_quartiles_and_n():
    rows = _rows([(ts(2026, 10, 1, 8), "a", v) for v in (10, 20, 30, 40)] + [(ts(2026, 10, 2, 8), "a", 7)])
    pts = build_series(rows, "tokens", "day", utc=True)["points"]
    assert [p["n"] for p in pts] == [4, 1]
    assert pts[0]["y"] == 25 and pts[0]["p25"] == 17.5 and pts[0]["p75"] == 32.5
    assert pts[0]["day"] == "2026-10-01"


def test_day_bucket_local_vs_utc():
    t = ts(2026, 10, 1, 2)
    assert day_key(t, utc=True) == "2026-10-01"
    local = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
    assert day_key(t) == local
    rows = _rows([(t, "a", 1)])
    assert build_series(rows, "tokens", "day", utc=True)["points"][0]["day"] == "2026-10-01"
    assert build_series(rows, "tokens", "day", utc=False)["points"][0]["day"] == local


def test_since_until_filter_applies_after_normalisation():
    rows = _rows([(ts(2026, 9, 27) * 1000, "a", 1), (ts(2026, 9, 30), "a", 2), (ts(2026, 10, 1), "a", 3)])
    out = build_series(rows, "tokens", "run", since=ts(2026, 9, 29), until="2026-10-01T23:59:59Z")
    assert [p["y"] for p in out["points"]] == [2, 3] and out["total_runs_in_range"] == 2


def test_missing_metric_is_skipped_not_zero():
    rows = _rows([(ts(2026, 10, 1), "a", 5)])
    rows.append({"run_id": "x", "session_id": "a", "created_at": ts(2026, 10, 2), "metrics_json": "{}"})
    out = build_series(rows, "tokens", "run")
    assert out["points_returned"] == 1 and out["total_runs_in_range"] == 2


def test_bad_params_raise():
    with pytest.raises(ValueError):
        build_series([], "nope")
    with pytest.raises(ValueError):
        build_series([], "tokens", "week")
    with pytest.raises(ValueError):
        build_series([], "tokens", since="xyz")


def test_downsample_only_above_max_points_keeps_range_and_order():
    spec = [(ts(2026, 9, 24) + i * 60, "a", (i * 37) % 101) for i in range(7000)]
    out = build_series(_rows(spec), "tokens", "run", max_points=500)
    xs = [p["x"] for p in out["points"]]
    assert out["sampled"] is True and len(xs) == 500 and out["total_runs_in_range"] == 7000
    assert xs == sorted(xs) and len(set(xs)) == 500
    assert xs[0] == spec[0][0] and xs[-1] == spec[-1][0]
    real = {t: v for t, _, v in spec}
    assert all(real[p["x"]] == p["y"] for p in out["points"])         # timestamp->value preserved
    small = build_series(_rows(spec[:400]), "tokens", "run", max_points=500)
    assert small["sampled"] is False and small["points_returned"] == 400


def test_downsample_happens_after_sorting_shuffled_input():
    spec = [(ts(2026, 9, 24) + i * 60, "a", i) for i in range(2000)]
    import random
    random.Random(1).shuffle(spec)
    xs = [p["x"] for p in build_series(_rows(spec), "tokens", "run", max_points=300)["points"]]
    assert xs == sorted(xs) and xs[0] == min(t for t, _, _ in spec) and xs[-1] == max(t for t, _, _ in spec)


def test_lttb_edge_cases():
    pts = [{"x": i, "y": i % 5} for i in range(10)]
    assert lttb(pts, 10) == pts and lttb(pts, 20) == pts
    assert len(lttb(pts, 3)) == 3


def test_metrics_cover_frontend_series_keys():
    assert set(METRICS) == {"tokens", "judge", "context", "saved", "amplification", "latency", "cost",
                            "documents", "recall", "precision"}
    m = {"jev_input_tokens": 30, "jev_output_tokens": 10, "context_tokens": 50, "jev_cost": 0.002,
         "model_cost": 0.001, "prefilter_tokens_saved_estimate": 5, "snippet_tokens_saved": 7,
         "expected_sources_found": {"found": 2, "recall": 0.5}, "documents_sent_to_model": 4}
    assert METRICS["judge"](m) == 40 and METRICS["tokens"](m) == 90
    assert METRICS["amplification"](m) == pytest.approx(1.8)
    assert METRICS["cost"](m) == pytest.approx(0.003) and METRICS["saved"](m) == 12
    assert METRICS["recall"](m) == 0.5 and METRICS["precision"](m) == 0.5
    assert METRICS["precision"]({"expected_sources_found": {"found": 1}}) is None
    assert METRICS["tokens"]({}) is None


def test_build_timeseries_groups_by_pipeline():
    rows = _rows([(ts(2026, 10, 1), "a", 1)]) + [{**r, "pipeline": "q"} for r in _rows([(ts(2026, 9, 1), "a", 2)])]
    out = build_timeseries(rows, "tokens", "run")
    assert set(out["series"]) == {"p", "q"}
    assert out["range"] == {"first": ts(2026, 9, 1), "last": ts(2026, 10, 1)}


# -- REST --------------------------------------------------------------------------------------
@pytest.fixture
def api(history_db):
    from app.api import routes

    class _GW:
        db = history_db

    app = FastAPI()
    app.include_router(routes.router)
    old = routes._state["gateway"]
    routes._state["gateway"] = _GW()
    try:
        yield TestClient(app)
    finally:
        routes._state["gateway"] = old


def test_rest_sessions_order_and_total(api):
    r = api.get("/benchmark/sessions?limit=2")
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "3"
    body = r.json()
    assert [s["session_id"] for s in body] == ["adhoc", "only-in-runs"]
    assert body[0]["last_run_at"] == ts(2026, 10, 1)


def test_rest_runs_after_27_sept_and_until_filter(api):
    r = api.get(f"/benchmark/runs?since={ts(2026, 9, 28)}")
    assert {x["run_id"] for x in r.json()} == {"a1", "a2", "a3", "orphan"}
    assert r.headers["X-Total-Count"] == "4"
    r = api.get(f"/benchmark/runs?since={ts(2026, 9, 28)}&until={ts(2026, 9, 30)}")
    assert {x["run_id"] for x in r.json()} == {"a1", "orphan", "a2"}


def test_rest_timeseries_reaches_oct_1(api):
    body = api.get("/benchmark/timeseries?metric=tokens&agg=run").json()
    pts = body["series"]["graphify_jev_opt"]["points"]
    assert pts[-1]["x"] == ts(2026, 10, 1) and body["range"]["last"] == ts(2026, 10, 1)
    assert body["sampled"] is False and body["total_runs_in_range"] == 8
    assert api.get("/benchmark/timeseries?metric=bogus").status_code == 422


def test_rest_timeseries_covers_more_than_5000_runs(api, history_db):
    base = ts(2026, 10, 1, 13)
    history_db.conn.executemany(
        "INSERT INTO runs (run_id, session_id, created_at, pipeline, warmup, mode, metrics_json)"
        " VALUES (?,?,?,?,0,'retrieval',?)",
        [(f"bulk{i}", "bulk", base + i, "baseline", json.dumps({"context_tokens": i})) for i in range(6014)])
    history_db.conn.commit()
    runs = api.get("/benchmark/runs?limit=5000")
    assert len(runs.json()) == 5000 and int(runs.headers["X-Total-Count"]) > 6000   # the old preload ceiling
    body = api.get("/benchmark/timeseries?metric=context&agg=run&pipeline=baseline&max_points=800").json()
    s = body["series"]["baseline"]
    assert s["total_runs_in_range"] == 6014 and s["sampled"] is True and s["points_returned"] == 800
    assert s["range"] == {"first": base, "last": base + 6013}
    daily = api.get("/benchmark/timeseries?metric=context&agg=day&pipeline=baseline").json()
    assert daily["sampled"] is False and daily["series"]["baseline"]["total_runs_in_range"] == 6014


def test_rest_history_summary(api):
    s = api.get("/benchmark/history/summary").json()
    assert s["total_runs"] == 8 and s["total_sessions"] == 3 and s["adhoc_runs"] == 4
    assert s["newest_run_at"] == ts(2026, 10, 1)
    assert s["runs_por_dia_utc"]["2026-10-01"] == 1
