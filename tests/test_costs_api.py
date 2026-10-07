"""/api/costs/* through a minimal FastAPI app (only this router + a tmp_path DB)."""
from __future__ import annotations

import csv
import io
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import costs as costs_api
from app.database.db import Database
from app.services.security import get_or_create_local_token
from tests.test_costs_ledger import jev_run, mk_run


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("MG_METRICS_ONLY", raising=False)
    db = Database(tmp_path / "api.db")
    app = FastAPI()
    app.include_router(costs_api.router)
    app.dependency_overrides[costs_api.get_db] = lambda: db
    token = get_or_create_local_token()
    tc = TestClient(app, client=("127.0.0.1", 50000))
    yield tc, db, {"X-MG-Token": token}
    db.conn.close()


def seed(db, n=3):
    now = time.time()
    for i in range(n):
        db.save_run(mk_run(f"b{i}", created_at=now - 10 + i, scope="projeto:alpha"))
    db.save_run(jev_run("j0", created_at=now - 1, scope="projeto:beta"))
    db._exec("INSERT INTO candidates VALUES ('j0','c1','n.md','sec',0.9,0.8,0.0,'KEEP',42)")


def test_summary_labels_and_project_filter(env):
    tc, db, _ = env
    seed(db)
    s = tc.get("/api/costs/summary?range=all").json()
    assert s["calls"] == 4
    assert s["context_tokens"] == {"value": 400, "origin": "estimated"}
    assert s["judge_tokens"]["origin"] == "measured" and s["judge_tokens"]["value"] == 1010
    assert s["cost_usd"]["value"] == 0.000042 and s["cost_usd"]["origin"] == "measured"
    assert tc.get("/api/costs/summary?range=all&project=alpha").json()["calls"] == 3
    assert tc.get("/api/costs/summary?range=bad").status_code == 422


def test_summary_empty_money_null(env):
    tc, _, _ = env
    s = tc.get("/api/costs/summary").json()
    assert s["calls"] == 0 and s["cost_usd"]["value"] is None and s["cost_usd"]["origin"] == "unavailable"


def test_calls_pagination_and_detail(env):
    tc, db, _ = env
    seed(db)
    p1 = tc.get("/api/costs/calls?limit=3").json()
    assert [i["run_id"] for i in p1["items"]] == ["j0", "b2", "b1"] and p1["next_cursor"]
    p2 = tc.get(f"/api/costs/calls?limit=3&cursor={p1['next_cursor']}").json()
    assert [i["run_id"] for i in p2["items"]] == ["b0"] and p2["next_cursor"] is None
    assert p1["items"][0]["query"] == "pergunta" and p1["items"][0]["cost_origin"] == "measured"
    d = tc.get("/api/costs/calls/j0").json()
    assert d["candidates"][0]["decision"] == "KEEP" and d["context"] == "ctx"
    assert tc.get("/api/costs/calls/nope").status_code == 404
    assert tc.get("/api/costs/calls?cursor=garbage").status_code == 400


def test_csv_export(env):
    tc, db, _ = env
    seed(db)
    r = tc.get("/api/costs/export.csv")
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 4 and "query" in rows[0]
    j = next(x for x in rows if x["run_id"] == "j0")
    assert j["project"] == "beta" and j["judge_tokens_origin"] == "measured" and j["cost_usd"] == "4.2e-05"
    assert next(x for x in rows if x["run_id"] == "b0")["context_tokens_origin"] == "estimated"


def test_metrics_only_mode(env, monkeypatch):
    tc, db, _ = env
    seed(db)
    monkeypatch.setenv("MG_METRICS_ONLY", "1")
    items = tc.get("/api/costs/calls").json()["items"]
    assert items and all("query" not in i for i in items)
    d = tc.get("/api/costs/calls/j0").json()
    assert not ({"query", "context", "answer"} & set(d)) and d["metrics_only"] is True
    csv_text = tc.get("/api/costs/export.csv").text
    assert "query" not in csv_text.splitlines()[0] and "pergunta" not in csv_text


def test_budget_requires_token_and_feeds_summary(env):
    tc, db, hdr = env
    body = {"period": "day", "ceiling_usd": 0.00005}
    assert tc.put("/api/costs/budget", json=body).status_code == 403
    assert tc.put("/api/costs/budget", json=body, headers={"X-MG-Token": "wrong"}).status_code == 403
    assert tc.put("/api/costs/budget", json={"period": "year", "ceiling_usd": 1}, headers=hdr).status_code == 422
    assert tc.put("/api/costs/budget", json=body, headers=hdr).json() == {"budgets": {"day": 0.00005}}
    seed(db)
    b = tc.get("/api/costs/summary?range=today").json()["budget"]
    assert b["day"]["status"] == "warn" and b["month"]["status"] == "ok"  # 4.2e-5 / 5e-5 = 84%
    tc.put("/api/costs/budget", json={"period": "day", "ceiling_usd": 0.00004}, headers=hdr)
    assert tc.get("/api/costs/summary").json()["budget"]["day"]["status"] == "exceeded"


def test_budget_refuses_non_local_client(env, tmp_path):
    _, db, hdr = env
    app = FastAPI()
    app.include_router(costs_api.router)
    app.dependency_overrides[costs_api.get_db] = lambda: db
    remote = TestClient(app, client=("10.0.0.5", 50000))
    assert remote.put("/api/costs/budget", json={"period": "day", "ceiling_usd": 1}, headers=hdr).status_code == 403


def test_stream_emits_existing_after_rowid_and_terminates(env):
    tc, db, _ = env
    seed(db, 1)
    with tc.stream("GET", "/api/costs/stream?after_rowid=0&max_events=2&poll_interval=0.01&max_seconds=5") as r:
        text = "".join(r.iter_text())
    assert text.count("event: call") == 2 and "event: end" in text and '"run_id"' in text


def test_stream_emits_new_run_live_and_max_seconds_ends(env):
    tc, db, _ = env

    def later():
        time.sleep(0.3)
        db.save_run(mk_run("live1"))

    threading.Thread(target=later, daemon=True).start()
    t0 = time.monotonic()
    with tc.stream("GET", "/api/costs/stream?max_seconds=2&poll_interval=0.05") as r:
        text = "".join(r.iter_text())
    assert "live1" in text and "event: end" in text and time.monotonic() - t0 < 6
    with tc.stream("GET", "/api/costs/stream?max_seconds=0.2&poll_interval=0.05") as r:
        assert "event: call" not in "".join(r.iter_text())
