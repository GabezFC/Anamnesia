"""Terminal hardening: content search (T10.8) e janitor/Ctrl+C do manager (sessões REST/WS removidas)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.terminals.backend import FakePtyBackend
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import Project, ProjectRegistry, search_content

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN}


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------ content search
@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("import os\nNeedle here\nother\n", encoding="utf-8")
    (root / "b.txt").write_text("nothing\nxx needle yy\n", encoding="utf-8")
    (root / "bin.dat").write_bytes(b"\x00\x01needle\x00")
    (root / "big.txt").write_text("needle\n" + "x" * 2000, encoding="utf-8")
    for d in (".git", "node_modules", ".venv"):
        (root / d).mkdir()
        (root / d / "f.txt").write_text("needle", encoding="utf-8")
    return root


def test_content_search_hits_lines_and_skips(tree):
    r = search_content(str(tree), "needle", max_file_bytes=1000)
    hits = {(h["path"], h["line"]) for h in r["results"]}
    assert hits == {("src/a.py", 2), ("b.txt", 2)}  # case-insensitive; binary/big/skipped dirs absent
    assert all(len(h["snippet"]) <= 170 for h in r["results"])
    assert "Needle here" in next(h for h in r["results"] if h["path"] == "src/a.py")["snippet"]
    assert r["truncated"] is False


def test_content_search_caps_and_budgets(tree):
    (tree / "many.txt").write_text("needle\n" * 50, encoding="utf-8")
    r = search_content(str(tree), "needle", cap=5)
    assert len(r["results"]) == 5 and r["truncated"] is True
    r = search_content(str(tree), "needle", max_total_bytes=1)
    assert r["truncated"] is True
    ticks = iter(range(0, 1000, 10))
    r = search_content(str(tree), "needle", max_seconds=5, clock=lambda: next(ticks))
    assert r["truncated"] is True  # fake clock jumps past the deadline


def test_content_search_binary_sniff_invalid_utf8(tree):
    (tree / "latin.txt").write_bytes(b"caf\xe9 needle\n" + b"\xff\xfe" * 10)
    r = search_content(str(tree), "needle", max_file_bytes=1000)
    assert "latin.txt" not in {h["path"] for h in r["results"]}


def test_content_search_never_follows_symlinks_or_escapes(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle", encoding="utf-8")
    try:
        os.symlink(outside, tree / "linkdir", target_is_directory=True)
        os.symlink(outside / "secret.txt", tree / "linkfile.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    r = search_content(str(tree), "needle", max_file_bytes=1000)
    assert all("secret" not in h["path"] and "link" not in h["path"] for h in r["results"])
    from app.terminals.projects import PathEscapeError

    for bad in ("..", "../outside", str(outside)):
        with pytest.raises(PathEscapeError):
            search_content(str(tree), "needle", bad)


# ------------------------------------------------------------------ janitor (fake clock)
def test_janitor_reaps_idle_session_with_fake_clock(tmp_path):
    now = [1000.0]
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    fake = FakePtyBackend()
    m = TerminalManager(backend=fake, idle_seconds=10, clock=lambda: now[0], environ={"PATH": "/bin"},
                        janitor_interval=0.01)
    try:
        assert m._janitor is None  # lazy: nothing before the first session
        s = m.create(proj, prof)
        assert m._janitor is not None and m._janitor.is_alive() and m._janitor.daemon
        time.sleep(0.1)
        assert s.state == "active" and fake.spawned[0].terminated == 0  # not idle long enough
        now[0] += 11
        assert wait_for(lambda: fake.spawned[0].terminated > 0)  # reaped without any create()/list() call
        assert wait_for(lambda: s.state == "ended")
    finally:
        m.close_all()
    assert m._janitor is None


def test_janitor_spares_sessions_with_clients_and_stops_on_close_all(tmp_path):
    now = [0.0]
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    fake = FakePtyBackend()
    m = TerminalManager(backend=fake, idle_seconds=10, clock=lambda: now[0], environ={"PATH": "/bin"},
                        janitor_interval=0.01)
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        s = m.create(proj, prof)
        m.subscribe(s.id, loop)
        now[0] += 1000
        time.sleep(0.15)
        assert fake.spawned[0].terminated == 0  # a connected client protects the session
        t = m._janitor
    finally:
        m.close_all()
        loop.close()
    assert t is not None and not t.is_alive()


def test_janitor_restarts_after_close_all(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    m = TerminalManager(backend=FakePtyBackend(), environ={"PATH": "/bin"}, janitor_interval=0.05)
    m.create(proj, prof)
    m.close_all()
    m.create(proj, prof)
    try:
        assert m._janitor is not None and m._janitor.is_alive()
        assert sum(t.name == "pty-janitor" and t.is_alive() for t in threading.enumerate()) >= 1
    finally:
        m.close_all()


# ------------------------------------------------------------------ Ctrl+C
def test_ctrl_c_forwarded_unmodified(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    fake = FakePtyBackend(echo=False)
    m = TerminalManager(backend=fake, environ={"PATH": "/bin"})
    try:
        s = m.create(proj, prof)
        m.write(s.id, b"\x03")
        m.write(s.id, "\x03")
        m.write(s.id, b"a\x03b\x04\x1a")
        assert b"".join(fake.spawned[0].written) == b"\x03\x03a\x03b\x04\x1a"
        assert fake.spawned[0].terminated == 0 and s.state == "active"  # the manager does not interpret it
    finally:
        m.close_all()
