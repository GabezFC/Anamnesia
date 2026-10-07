"""Workspace REST + WebSocket API with a minimal FastAPI app and the Fake PTY backend."""
from __future__ import annotations

import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import workspace as ws_api
from app.terminals.backend import FakePtyBackend
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.delenv("MG_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv(ws_api.ALLOW_REMOTE_ENV, raising=False)


@pytest.fixture
def ctx(env, tmp_path):
    fake = FakePtyBackend()
    mgr = TerminalManager(backend=fake, max_sessions=2, environ={"PATH": "/bin"})
    reg = ProjectRegistry(tmp_path / "anamnesia.db")
    profiles = {
        "shell": Profile(id="shell", name="Shell", command=sys.executable, kind="shell"),
        "ghost": Profile(id="ghost", name="Ghost", command="no-such-cmd-xyz"),
    }
    app = FastAPI()
    app.include_router(ws_api.router)
    app.dependency_overrides[ws_api.get_manager] = lambda: mgr
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    app.dependency_overrides[ws_api.get_profiles] = lambda: profiles
    proj_dir = tmp_path / "work"
    (proj_dir / "src").mkdir(parents=True)
    (proj_dir / "src" / "main.py").write_text("x")
    (proj_dir / "README.md").write_text("x")
    client = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    remote = TestClient(app, client=("192.168.1.50", 51234), base_url=ORIGIN)
    yield type("Ctx", (), dict(app=app, client=client, remote=remote, mgr=mgr, reg=reg, fake=fake,
                               proj_dir=proj_dir))
    mgr.close_all()


def new_session(c, project_id, profile="shell"):
    r = c.client.post("/api/sessions", json={"project": project_id, "profile": profile}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def add_project(c):
    r = c.client.post("/api/projects", json={"name": "w", "path": str(c.proj_dir)}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def connect(c, sid, token=TOKEN, origin=ORIGIN, client=None, protos=None):
    headers = {"host": "127.0.0.1:8000"}
    if origin is not None:
        headers["origin"] = origin
    protos = protos if protos is not None else ([f"tok.{token}"] if token else [])
    return (client or c.client).websocket_connect(f"/api/sessions/{sid}/ws", subprotocols=protos,
                                                  headers=headers)


# ------------------------------------------------------------------ REST
def test_projects_crud_and_auth(ctx):
    assert ctx.client.post("/api/projects", json={"name": "w", "path": str(ctx.proj_dir)}).status_code == 403
    assert ctx.remote.post("/api/projects", json={"name": "w", "path": str(ctx.proj_dir)},
                           headers=H).status_code == 403
    pid = add_project(ctx)
    assert [p["id"] for p in ctx.client.get("/api/projects").json()["projects"]] == [pid]
    assert ctx.remote.get("/api/projects").status_code == 403
    bad = ctx.client.post("/api/projects", json={"name": "n", "path": str(ctx.proj_dir / "nope")}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_project"
    assert ctx.client.delete(f"/api/projects/{pid}").status_code == 403
    assert ctx.client.delete(f"/api/projects/{pid}", headers=H).status_code == 200
    assert ctx.client.delete(f"/api/projects/{pid}", headers=H).status_code == 404
    assert (ctx.proj_dir / "README.md").exists()


def test_files_listing_search_and_escape(ctx):
    pid = add_project(ctx)
    url = f"/api/projects/{pid}/files"
    assert ctx.client.get(url).status_code == 403  # token required
    r = ctx.client.get(url, headers=H).json()
    assert [e["name"] for e in r["entries"]] == ["src", "README.md"]
    assert [e["name"] for e in ctx.client.get(url, params={"path": "src"}, headers=H).json()["entries"]] == ["main.py"]
    s = ctx.client.get(url, params={"q": "MAIN"}, headers=H).json()
    assert [x["path"] for x in s["results"]] == ["src/main.py"]
    for evil in ("..", "../..", "src/../..", "/etc"):
        r = ctx.client.get(url, params={"path": evil}, headers=H)
        assert r.status_code == 403 and r.json()["error"]["code"] == "path_escape"
    assert ctx.client.get("/api/projects/nope/files", headers=H).status_code == 404


def test_profiles_endpoint(ctx):
    r = ctx.client.get("/api/profiles").json()["profiles"]
    by = {p["id"]: p for p in r}
    assert by["shell"]["available"] is True and by["ghost"]["available"] is False


def test_session_lifecycle_rest(ctx):
    pid = add_project(ctx)
    assert ctx.client.post("/api/sessions", json={"project": pid}).status_code == 403
    r = ctx.client.post("/api/sessions", json={"project": pid, "profile": "shell", "cols": 100, "rows": 30},
                        headers=H)
    assert r.status_code == 201
    sid = r.json()["session_id"]
    assert r.json()["ws_url"] == f"/api/sessions/{sid}/ws"
    assert ctx.client.get("/api/sessions").status_code == 403
    lst = ctx.client.get("/api/sessions", headers=H).json()["sessions"]
    assert [s["id"] for s in lst] == [sid] and lst[0]["state"] == "active" and lst[0]["cols"] == 100
    assert "env" not in lst[0]
    assert ctx.client.delete(f"/api/sessions/{sid}").status_code == 403
    assert ctx.client.delete(f"/api/sessions/{sid}", headers=H).status_code == 200
    assert ctx.client.delete(f"/api/sessions/{sid}", headers=H).status_code == 404
    assert ctx.fake.spawned[0].terminated == 1


def test_session_errors(ctx):
    pid = add_project(ctx)
    post = lambda body: ctx.client.post("/api/sessions", json=body, headers=H)  # noqa: E731
    assert post({"project": "nope"}).json()["error"]["code"] == "project_not_found"
    assert post({"project": pid, "profile": "zzz"}).json()["error"]["code"] == "profile_not_found"
    r = post({"project": pid, "profile": "ghost"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "profile_unavailable"
    new_session(ctx, pid)
    new_session(ctx, pid)
    r = post({"project": pid, "profile": "shell"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "session_limit"


def test_remote_host_gate_rest(ctx, monkeypatch):
    pid = add_project(ctx)
    monkeypatch.setenv("MG_HOST", "0.0.0.0")
    r = ctx.client.post("/api/sessions", json={"project": pid}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "terminals_disabled"
    assert ctx.client.get("/api/sessions", headers=H).status_code == 403
    assert ctx.fake.spawned == []
    monkeypatch.setenv(ws_api.ALLOW_REMOTE_ENV, "1")
    assert ctx.client.post("/api/sessions", json={"project": pid}, headers=H).status_code == 201


# ------------------------------------------------------------------ WebSocket
def expect_4403(cm):
    with pytest.raises(WebSocketDisconnect) as e:
        with cm:
            pass
    assert e.value.code == 4403


def test_ws_rejections(ctx):
    sid = new_session(ctx, add_project(ctx))
    expect_4403(connect(ctx, sid, token=None))                      # no token
    expect_4403(connect(ctx, sid, token="wrong"))                   # bad token
    expect_4403(connect(ctx, sid, origin="http://evil.example"))    # bad Origin
    expect_4403(connect(ctx, sid, origin="http://127.0.0.1:9999"))  # other port
    expect_4403(connect(ctx, sid, origin=None))                     # no Origin
    expect_4403(connect(ctx, sid, client=ctx.remote))               # non-loopback client
    expect_4403(connect(ctx, sid, protos=["other", "tok."]))        # not the token
    expect_4403(connect(ctx, "does-not-exist", token="wrong"))      # wrong token reveals nothing
    assert ctx.fake.spawned[0].written == []


def test_ws_token_in_url_is_not_accepted(ctx):
    sid = new_session(ctx, add_project(ctx))
    cm = ctx.client.websocket_connect(f"/api/sessions/{sid}/ws?token={TOKEN}",
                                      headers={"origin": ORIGIN, "host": "127.0.0.1:8000"})
    expect_4403(cm)


def test_ws_unknown_session_with_valid_auth(ctx):
    with pytest.raises(WebSocketDisconnect) as e:
        with connect(ctx, "nope"):
            pass
    assert e.value.code == 4404


def test_ws_dns_rebinding_host_rejected(ctx):
    sid = new_session(ctx, add_project(ctx))
    c = TestClient(ctx.app, client=("127.0.0.1", 1))
    expect_4403(c.websocket_connect(f"/api/sessions/{sid}/ws", subprotocols=[f"tok.{TOKEN}"],
                                    headers={"host": "evil.example:8000", "origin": "http://evil.example:8000"}))


def drain_until(ws, needle: bytes, limit=20):
    seen = b""
    for _ in range(limit):
        m = ws.receive()
        if m.get("bytes") is not None:
            seen += m["bytes"]
            if needle in seen:
                return seen
    raise AssertionError(f"never saw {needle!r}; got {seen!r}")


def test_ws_echo_resize_replay_and_survives_reconnect(ctx):
    sid = new_session(ctx, add_project(ctx))
    with connect(ctx, sid) as ws:
        assert ws.accepted_subprotocol == f"tok.{TOKEN}"
        first = ws.receive_json()
        assert first == {"t": "replay", "bytes": 0}
        assert ws.receive_json() == {"t": "state", "v": "active"}
        ws.send_bytes(b"ping1")
        drain_until(ws, b"ping1")
        ws.send_text('{"t":"in","d":"ping2"}')
        drain_until(ws, b"ping2")
        ws.send_text('{"t":"resize","cols":120,"rows":30}')
        ws.send_text('{"t":"rs","rows":31,"cols":121}')
        ws.send_text("not json")  # ignored, must not kill the connection
        ws.send_bytes(b"ping3")
        drain_until(ws, b"ping3")
    h = ctx.fake.spawned[0]
    assert h.written == [b"ping1", b"ping2", b"ping3"]
    assert h.resizes == [(30, 120), (31, 121)]
    assert h.terminated == 0  # the session survives the disconnect
    with connect(ctx, sid) as ws2:  # reconnect: buffer replayed
        head = ws2.receive_json()
        assert head["t"] == "replay" and head["bytes"] == len(b"ping1ping2ping3")
        assert ws2.receive_bytes() == b"ping1ping2ping3"


def test_ws_child_exit_sends_state_and_closes(ctx):
    sid = new_session(ctx, add_project(ctx))
    with connect(ctx, sid) as ws:
        ws.receive_json(); ws.receive_json()  # noqa: E702
        ctx.fake.spawned[0].finish(7)
        msgs = []
        for _ in range(10):
            m = ws.receive()
            if m["type"] == "websocket.close":
                break
            if m.get("text"):
                msgs.append(m["text"])
        assert any('"ended"' in t and '"code": 7' in t for t in msgs), msgs


def test_ws_remote_gate_and_override(ctx, monkeypatch):
    sid = new_session(ctx, add_project(ctx))
    monkeypatch.setenv("MG_HOST", "0.0.0.0")
    expect_4403(connect(ctx, sid))
    monkeypatch.setenv(ws_api.ALLOW_REMOTE_ENV, "1")
    with connect(ctx, sid) as ws:
        assert ws.receive_json()["t"] == "replay"
    expect_4403(connect(ctx, sid, client=ctx.remote))  # override never allows non-loopback clients


def test_audit_log_has_no_secrets_or_keystrokes(ctx, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="anamnesia.terminals.audit")
    sid = new_session(ctx, add_project(ctx))
    with connect(ctx, sid) as ws:
        ws.receive_json(); ws.receive_json()  # noqa: E702
        ws.send_bytes(b"supersecretkeystrokes")
        drain_until(ws, b"supersecretkeystrokes")
    ctx.client.delete(f"/api/sessions/{sid}", headers=H)
    text = caplog.text
    assert "session_open" in text and "session_close" in text
    assert TOKEN not in text and "supersecretkeystrokes" not in text
    time.sleep(0)
