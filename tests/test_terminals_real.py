"""Real PTY backends: POSIX pty (skipped on Windows) and ONE real pywinpty test (Windows only)."""
from __future__ import annotations

import sys
import time

import pytest

from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import Project


def wait_for(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _winpty_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winpty  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def proj(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return Project("p1", "real", str(d), time.time())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only")
def test_posix_backend_echo_cwd_env_and_kill(proj, tmp_path):
    from app.terminals.backend import PosixPtyBackend

    secret_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "FAKE_SECRET_TOKEN": "leak-me"}
    m = TerminalManager(backend=PosixPtyBackend(), environ=secret_env)
    prof = Profile(id="sh", name="sh", command="sh", kind="agent")
    s = m.create(proj, prof, cols=100, rows=30)
    try:
        m.write(s.id, "pwd; echo secret=${FAKE_SECRET_TOKEN:-none}; stty size; echo done-marker\n")
        assert wait_for(lambda: b"done-marker" in bytes(s.ring) and b"30 100" in bytes(s.ring))
        out = bytes(s.ring).decode(errors="replace")
        assert "secret=none" in out and "leak-me" not in out
        assert proj.path in out or proj.path.replace("\\", "/") in out
        m.resize(s.id, 40, 120)
        m.write(s.id, "stty size; echo resized-marker\n")
        assert wait_for(lambda: b"40 120" in bytes(s.ring))
        pid = s.pid
    finally:
        m.close(s.id)
    assert s.state == "ended"
    import os

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only")
def test_posix_close_kills_whole_process_group(proj):
    import os

    from app.terminals.backend import PosixPtyBackend

    m = TerminalManager(backend=PosixPtyBackend(), environ={"PATH": "/usr/bin:/bin"})
    s = m.create(proj, Profile(id="sh", name="sh", command="sh"))
    m.write(s.id, "sleep 300 &\necho CHILD=$!\n")
    assert wait_for(lambda: b"CHILD=" in bytes(s.ring) and bytes(s.ring).count(b"CHILD=") >= 2)
    import re

    child = int(re.findall(rb"CHILD=(\d+)", bytes(s.ring))[-1])
    m.close(s.id)
    assert wait_for(lambda: not _alive(child), 5)


def _alive(pid: int) -> bool:
    import os

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie still answers kill(0); treat reparented/dead as gone via /proc when available
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


@pytest.mark.skipif(not _winpty_available(), reason="needs Windows + pywinpty")
def test_winpty_real_cmd_echo(proj):
    from app.terminals.backend import WinPtyBackend

    m = TerminalManager(backend=WinPtyBackend())
    prof = Profile(id="cmd", name="cmd", command="cmd.exe", args=("/c", "echo anamnesia"))
    s = m.create(proj, prof)
    try:
        assert wait_for(lambda: b"anamnesia" in bytes(s.ring), 20)
        assert wait_for(lambda: s.state == "ended", 20)
    finally:
        m.close(s.id)
    assert m.list() == []
