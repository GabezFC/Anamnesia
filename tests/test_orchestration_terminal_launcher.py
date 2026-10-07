"""TerminalLauncher over the Terminal Manager with FakePtyBackend (no real process, no network)."""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from app.orchestration.launchers import SessionLauncher, TerminalLauncher
from app.orchestration.orchestrator import Orchestrator
from app.terminals.backend import FakePtyBackend
from app.terminals.manager import SessionLimitError, TerminalManager
from app.terminals.profiles import Profile
from tests.orch_helpers import cfg, project, three

ENVIRON = {"PATH": "/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "should-not-leak"}
PROFILES = {"agent": Profile(id="agent", name="Agent", command=sys.executable)}


def make(tmp_path, backend=None, **kw):
    backend = backend or FakePtyBackend()
    mgr = TerminalManager(backend=backend, environ=ENVIRON, **kw.pop("mgr", {}))
    return TerminalLauncher(mgr, PROFILES, default_profile_id="agent", **kw), mgr, backend


def test_protocol_and_launch_env(tmp_path):
    L, mgr, be = make(tmp_path)
    assert isinstance(L, SessionLauncher)
    d = project(tmp_path)
    sid = L.launch("p1", "agent", {"ANAMNESIA_ROLE": "researcher", "ANAMNESIA_MODEL": "m-t1"}, str(d))
    h = be.spawned[0]
    assert h.env["ANAMNESIA_ROLE"] == "researcher" and h.env["ANAMNESIA_MODEL"] == "m-t1"
    assert "ANTHROPIC_API_KEY" not in h.env
    assert Path(h.cwd) == Path(d)
    assert L.is_alive(sid)
    L.close(sid)
    assert not L.is_alive(sid) and mgr.list() == []
    L.close(sid)  # idempotent


def test_env_is_per_spawn_not_sticky(tmp_path):
    L, _, be = make(tmp_path)
    d = str(project(tmp_path))
    L.launch(None, "agent", {"ANAMNESIA_STEP": "a"}, d)
    L.launch(None, "agent", {}, d)
    assert be.spawned[0].env["ANAMNESIA_STEP"] == "a"
    assert "ANAMNESIA_STEP" not in be.spawned[1].env


def test_rejects_non_anamnesia_env_and_unknown_profile(tmp_path):
    L, mgr, be = make(tmp_path)
    d = str(project(tmp_path))
    with pytest.raises(ValueError):
        L.launch(None, "agent", {"ANTHROPIC_API_KEY": "x"}, d)
    with pytest.raises(ValueError):
        L.launch(None, "nope", {}, d)
    assert be.spawned == [] and mgr.list() == []


def test_session_limit_raises_and_leaves_nothing(tmp_path):
    L, mgr, _ = make(tmp_path, mgr={"max_sessions": 1})
    d = str(project(tmp_path))
    a = L.launch(None, "agent", {}, d)
    with pytest.raises(SessionLimitError):
        L.launch(None, "agent", {}, d)
    assert [s.id for s in mgr.list()] == [a]


def test_send_writes_text_with_submit(tmp_path):
    L, _, be = make(tmp_path)
    sid = L.launch(None, "agent", {}, str(project(tmp_path)))
    L.send(sid, "hello\nworld\n")
    assert be.spawned[0].written == [b"hello\nworld\r"]


def test_send_to_dead_session_closes_and_raises(tmp_path):
    L, mgr, be = make(tmp_path)
    sid = L.launch(None, "agent", {}, str(project(tmp_path)))
    be.spawned[0].finish(1)
    deadline = time.time() + 5
    while L.is_alive(sid) and time.time() < deadline:
        time.sleep(0.01)
    with pytest.raises(RuntimeError):
        L.send(sid, "x")
    assert not L.is_alive(sid)


def test_process_exit_is_not_alive(tmp_path):
    L, _, be = make(tmp_path)
    sid = L.launch(None, "agent", {}, str(project(tmp_path)))
    be.spawned[0].finish(0)
    deadline = time.time() + 5
    while L.is_alive(sid) and time.time() < deadline:
        time.sleep(0.01)
    assert not L.is_alive(sid)


def test_max_session_age_closes_session(tmp_path):
    now = [0.0]
    L, mgr, be = make(tmp_path, max_session_s=10, clock=lambda: now[0])
    sid = L.launch(None, "agent", {}, str(project(tmp_path)))
    assert L.is_alive(sid)
    now[0] = 11.0
    assert not L.is_alive(sid)
    assert be.spawned[0].terminated == 1 and mgr.list() == []


def _agent(be, stop, behavior):
    """Simulated agent: for each spawned session, write result.md/status.json from its own env."""
    done = set()
    while not stop.is_set():
        for h in list(be.spawned):
            if id(h) in done or not h.written:
                continue
            done.add(id(h))
            sd = Path(h.env["ANAMNESIA_STEP_DIR"])
            ok = behavior(h)
            if ok:
                (sd / "result.md").write_text(f"done by {h.env['ANAMNESIA_ROLE']}", encoding="utf-8")
            (sd / "status.json").write_text(json.dumps(
                {"ok": ok, "error": None if ok else "boom", "input_tokens": None, "output_tokens": None}),
                encoding="utf-8")
        time.sleep(0.01)


def run_orch(tmp_path, behavior, **limits):
    be = FakePtyBackend(echo=False)
    L, mgr, _ = make(tmp_path, be)
    o = Orchestrator(L, registry=three(tmp_path), config=cfg(**limits), profile_id="agent", sync=True)
    stop = threading.Event()
    t = threading.Thread(target=_agent, args=(be, stop, behavior), daemon=True)
    t.start()
    try:
        rid = o.submit("Corrigir o bug", "balanced", project(tmp_path))
    finally:
        stop.set()
        t.join(2)
    return o, rid, mgr, be


def test_orchestrator_end_to_end_reads_step_files_and_closes_sessions(tmp_path):
    o, rid, mgr, be = run_orch(tmp_path, lambda h: True)
    s = o.get(rid, project(tmp_path)).summary
    assert s["state"] == "done", s
    assert [st["state"] for st in s["steps"]] == ["done"] * 3
    assert len(be.spawned) == 3 and mgr.list() == []
    assert all(h.env["ANAMNESIA_RUN_ID"] == rid and h.env["ANAMNESIA_MODEL_ID"] for h in be.spawned)


def test_failures_never_leave_sessions_open(tmp_path):
    o, rid, mgr, be = run_orch(tmp_path, lambda h: False)
    assert o.get(rid, project(tmp_path)).summary["state"] == "failed"
    assert be.spawned and mgr.list() == []


def test_step_timeout_closes_session(tmp_path):
    be = FakePtyBackend(echo=False)
    L, mgr, _ = make(tmp_path, be)
    o = Orchestrator(L, registry=three(tmp_path), config=cfg(step_timeout_s=0.2), profile_id="agent", sync=True)
    rid = o.submit("Corrigir o bug", "balanced", project(tmp_path))  # nobody writes result files
    s = o.get(rid, project(tmp_path)).summary
    assert s["state"] == "failed"
    assert be.spawned and mgr.list() == []
    assert all(h.terminated >= 1 for h in be.spawned)


@pytest.mark.skipif(sys.platform == "win32" and not __import__("importlib").util.find_spec("winpty"),
                    reason="needs pywinpty on Windows")
def test_real_pty_roundtrip(tmp_path):
    from app.terminals.backend import default_backend
    prof = {"py": Profile(id="py", name="py", command=sys.executable, args=("-u", "-c", "print('ok-pty'); import time; time.sleep(30)"))}
    mgr = TerminalManager(backend=default_backend())
    L = TerminalLauncher(mgr, prof, default_profile_id="py")
    sid = None
    try:
        sid = L.launch(None, "py", {"ANAMNESIA_ROLE": "researcher"}, str(project(tmp_path)))
        assert L.is_alive(sid)
    finally:
        if sid:
            L.close(sid)
        mgr.close_all()
    assert not L.is_alive(sid)
