"""/api/orchestration/* through a minimal FastAPI app."""
from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import orchestration as api
from app.orchestration.launchers import FakeLauncher
from app.services.security import get_or_create_local_token
from tests.orch_helpers import orch, project


def make(tmp_path, sync=True, launcher=None):
    o, fl = orch(tmp_path, launcher=launcher, sync=sync)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_orchestrator] = lambda: o
    tc = TestClient(app, client=("127.0.0.1", 50000))
    return tc, o, fl, {"X-MG-Token": get_or_create_local_token()}


def test_presets(tmp_path):
    tc, *_ = make(tmp_path)
    d = tc.get("/api/orchestration/presets").json()
    assert [p["name"] for p in d["presets"]] == ["economic", "balanced", "max"]
    assert d["class_tiers"] == {"cheap": [1], "medium": [2], "strong": [3]}
    assert d["limits"]["max_parallel_subagents"] == 3


def test_post_requires_token(tmp_path):
    tc, o, fl, h = make(tmp_path)
    body = {"path": str(project(tmp_path)), "task": "x", "preset": "economic"}
    assert tc.post("/api/orchestration/runs", json=body).status_code == 403
    assert tc.post("/api/orchestration/runs", json=body, headers={"X-MG-Token": "wrong"}).status_code == 403
    assert tc.post("/api/orchestration/runs/abc/cancel").status_code == 403
    remote = TestClient(tc.app, client=("10.0.0.5", 1))
    assert remote.post("/api/orchestration/runs", json=body, headers=h).status_code == 403
    assert fl.calls == [] and not (project(tmp_path) / ".anamnesia").exists()


def test_create_get_list(tmp_path):
    tc, o, fl, h = make(tmp_path)
    p = str(project(tmp_path))
    r = tc.post("/api/orchestration/runs", json={"path": p, "task": "fix it", "preset": "economic",
                                                 "project_id": "alpha"}, headers=h)
    assert r.status_code == 202
    rid = r.json()["run_id"]
    d = tc.get(f"/api/orchestration/runs/{rid}", params={"path": p}).json()
    assert d["state"] == "done" and d["project_id"] == "alpha" and d["events"]
    lst = tc.get("/api/orchestration/runs", params={"path": p}).json()["runs"]
    assert [x["run_id"] for x in lst] == [rid]


def test_validation_errors(tmp_path):
    tc, o, fl, h = make(tmp_path)
    p = str(project(tmp_path))
    assert tc.post("/api/orchestration/runs", json={"path": p, "task": "x", "preset": "turbo"},
                   headers=h).status_code == 400
    assert tc.post("/api/orchestration/runs", json={"path": str(tmp_path / "nope"), "task": "x"},
                   headers=h).status_code == 400
    assert tc.post("/api/orchestration/runs", json={"path": p, "task": ""}, headers=h).status_code == 422
    assert tc.post("/api/orchestration/runs", json={"path": p, "task": "x", "budget_usd": -1},
                   headers=h).status_code == 422


def test_get_unknown_and_traversal(tmp_path):
    tc, *_ = make(tmp_path)
    p = str(project(tmp_path))
    assert tc.get("/api/orchestration/runs/nope", params={"path": p}).status_code == 404
    assert tc.get("/api/orchestration/runs/..%2F..%2Fx", params={"path": p}).status_code == 404
    assert tc.get("/api/orchestration/runs/nope").status_code == 404


def test_cancel_running(tmp_path):
    ev = threading.Event()
    fl = FakeLauncher(behavior=lambda c: {"block": ev}, input_tokens=1, output_tokens=1)
    tc, o, _, h = make(tmp_path, sync=False, launcher=fl)
    p = str(project(tmp_path))
    rid = tc.post("/api/orchestration/runs", json={"path": p, "task": "x", "preset": "balanced"},
                  headers=h).json()["run_id"]
    for _ in range(300):
        if fl.calls:
            break
        threading.Event().wait(0.01)
    r = tc.post(f"/api/orchestration/runs/{rid}/cancel", params={"path": p}, headers=h)
    assert r.status_code == 200 and r.json()["result"] == "cancelling"
    ev.set()
    o.wait(rid, 10)
    assert tc.get(f"/api/orchestration/runs/{rid}", params={"path": p}).json()["state"] == "cancelled"
    assert tc.post("/api/orchestration/runs/missing/cancel", params={"path": p}, headers=h).status_code == 404


def test_run_survives_restart_via_disk(tmp_path):
    tc, o, fl, h = make(tmp_path)
    p = str(project(tmp_path))
    rid = tc.post("/api/orchestration/runs", json={"path": p, "task": "x"}, headers=h).json()["run_id"]
    tc2, *_ = make(tmp_path)          # fresh orchestrator, no in-memory runs
    assert tc2.get(f"/api/orchestration/runs/{rid}", params={"path": p}).json()["state"] == "done"
