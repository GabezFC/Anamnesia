"""Terminal Manager with the in-memory FakePtyBackend: no real process is spawned."""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

from app.terminals.backend import FakePtyBackend
from app.terminals.manager import (ENV_ALLOWLIST, SessionLimitError, SessionNotFound, TerminalManager,
                                   build_env)
from app.terminals.profiles import Profile, ProfileUnavailable
from app.terminals.projects import Project


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return Project("p1", "meuprojeto", str(d), time.time())


@pytest.fixture
def prof():
    return Profile(id="agent", name="Agent", command=sys.executable, env_keys=("FAKE_PROFILE_KEY",))


@pytest.fixture
def fake():
    return FakePtyBackend()


ENVIRON = {"PATH": "/bin", "HOME": "/var/fakehome", "FAKE_SECRET_TOKEN": "s3cret", "FAKE_PROFILE_KEY": "pk",
           "LANG": "C", "ANTHROPIC_API_KEY": "should-not-leak"}


def mk(fake, **kw):
    kw.setdefault("environ", ENVIRON)
    return TerminalManager(backend=fake, **kw)


def test_create_list_get_close(fake, proj, prof):
    m = mk(fake)
    s = m.create(proj, prof, cols=100, rows=30)
    assert s.state == "active" and s.pid
    assert [x.id for x in m.list()] == [s.id]
    assert m.get(s.id) is s
    assert s.to_dict()["rows"] == 30 and s.to_dict()["cols"] == 100
    assert m.close(s.id) is True
    assert fake.spawned[0].terminated == 1
    assert s.state == "ended"
    assert m.list() == []
    with pytest.raises(SessionNotFound):
        m.get(s.id)
    assert m.close(s.id) is False


def test_max_sessions(fake, proj, prof):
    m = mk(fake, max_sessions=2)
    a = m.create(proj, prof)
    m.create(proj, prof)
    with pytest.raises(SessionLimitError):
        m.create(proj, prof)
    m.close(a.id)
    m.create(proj, prof)  # a slot freed


def test_max_sessions_env(monkeypatch, fake):
    monkeypatch.setenv("ANAMNESIA_MAX_SESSIONS", "3")
    assert TerminalManager(backend=fake).max_sessions == 3
    monkeypatch.setenv("ANAMNESIA_MAX_SESSIONS", "abc")
    assert TerminalManager(backend=fake).max_sessions == 8


def test_env_allowlist_and_profile_keys(fake, proj, prof):
    m = mk(fake)
    m.create(proj, prof)
    env = fake.spawned[0].env
    assert "FAKE_SECRET_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["FAKE_PROFILE_KEY"] == "pk"  # declared by the profile
    assert env["PATH"] == "/bin" and env["HOME"] == "/var/fakehome" and env["LANG"] == "C"
    assert env["MG_SCOPE"] == "meuprojeto"
    assert env["TERM"]
    assert not (set(env) - {k for k in ENV_ALLOWLIST} - {"FAKE_PROFILE_KEY", "MG_SCOPE"})


def test_env_case_insensitive_and_real_environ(monkeypatch):
    monkeypatch.setenv("FAKE_SECRET_TOKEN", "zzz")
    env = build_env(())
    assert "FAKE_SECRET_TOKEN" not in env
    assert "x" in build_env((), {"path": "x"}).values()


def test_cwd_forced_to_project(fake, proj, prof):
    m = mk(fake)
    s = m.create(proj, prof)
    assert os.path.realpath(fake.spawned[0].cwd) == os.path.realpath(proj.path)
    assert s.project_path == os.path.realpath(proj.path)


def test_missing_project_dir_and_command(fake, proj, prof):
    m = mk(fake)
    gone = Project("x", "x", proj.path + "_nope", 0)
    with pytest.raises(FileNotFoundError):
        m.create(gone, prof)
    bad = Profile(id="b", name="b", command="definitely-not-a-real-command-xyz")
    with pytest.raises(ProfileUnavailable):
        m.create(proj, bad)
    assert fake.spawned == []


def test_idle_expiry_only_without_clients(fake, proj, prof):
    now = [1000.0]
    m = mk(fake, idle_seconds=60, clock=lambda: now[0])
    a = m.create(proj, prof)
    b = m.create(proj, prof)
    loop = asyncio.new_event_loop()
    try:
        sub, _ = m.subscribe(b.id, loop)  # b has a client
        now[0] += 61
        assert m.reap() == [a.id]
        assert fake.spawned[0].terminated == 1 and fake.spawned[1].terminated == 0
        assert [s.id for s in m.list()] == [b.id]
        m.unsubscribe(b.id, sub)  # detach restarts the idle clock
        now[0] += 30
        assert m.reap() == []
        now[0] += 31
        assert m.reap() == [b.id]
    finally:
        loop.close()


def test_ring_buffer_replay_truncates(fake, proj, prof):
    m = mk(fake, ring_bytes=16)
    s = m.create(proj, prof)
    h = fake.spawned[0]
    h.emit(b"A" * 10)
    h.emit(b"B" * 10)
    h.emit(b"C" * 10)
    assert wait_for(lambda: s.ring.endswith(b"C" * 10) and len(s.ring) == 16)
    loop = asyncio.new_event_loop()
    try:
        _, replay = m.subscribe(s.id, loop)
        assert replay == b"B" * 6 + b"C" * 10
    finally:
        loop.close()


def test_live_output_reaches_subscriber(fake, proj, prof):
    m = mk(fake)
    s = m.create(proj, prof)

    async def go():
        sub, replay = m.subscribe(s.id, asyncio.get_running_loop())
        assert replay == b""
        m.write(s.id, "hello")  # fake echoes
        got = await asyncio.wait_for(sub.queue.get(), 5)
        assert got == b"hello"
        fake.spawned[0].finish(3)
        assert await asyncio.wait_for(sub.queue.get(), 5) is None
        assert wait_for(lambda: s.state == "ended")
        assert s.exit_code == 3

    asyncio.run(go())
    assert fake.spawned[0].written == [b"hello"]


def test_resize_forwarded_and_clamped(fake, proj, prof):
    m = mk(fake)
    s = m.create(proj, prof, cols=80, rows=24)
    m.resize(s.id, 30, 120)
    assert fake.spawned[0].resizes == [(30, 120)]
    assert (s.rows, s.cols) == (30, 120)
    m.resize(s.id, 0, 99999)
    assert fake.spawned[0].resizes[-1] == (1, 500)


def test_natural_exit_marks_ended_and_frees_slot(fake, proj, prof):
    m = mk(fake, max_sessions=1)
    s = m.create(proj, prof)
    fake.spawned[0].finish(0)
    assert wait_for(lambda: s.state == "ended")
    m.create(proj, prof)  # ended sessions do not count against the limit
    m.write(s.id, "x")  # no error writing to an ended session


def test_close_all(fake, proj, prof):
    m = mk(fake)
    for _ in range(3):
        m.create(proj, prof)
    m.close_all()
    assert all(h.terminated == 1 for h in fake.spawned) and m.list() == []
