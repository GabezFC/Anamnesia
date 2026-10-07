"""Windows Job Object (KILL_ON_JOB_CLOSE) with a REAL pywinpty session. Skipped unless Windows + pywinpty."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

try:
    import winpty  # noqa: F401
    HAVE = sys.platform == "win32"
except ImportError:
    HAVE = False

pytestmark = pytest.mark.skipif(not HAVE, reason="needs Windows + pywinpty")

from app.terminals.manager import TerminalManager  # noqa: E402
from app.terminals.profiles import Profile  # noqa: E402
from app.terminals.projects import Project  # noqa: E402
from app.terminals import backend as be  # noqa: E402


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True).stdout.decode("latin-1")
    return f" {pid} " in out


def _wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def _grandchild_pid(m, s, marker: str) -> int:
    """Start `cmd /c start /b python -c <sleep>` from the session shell; return the sleeper's PID."""
    py = sys.executable
    m.write(s.id, f'cmd /c start /b "" "{py}" -c "import os,time;print(\'{marker}\',os.getpid(),flush=True);'
                  f'time.sleep(300)"\r\n')
    import re

    assert _wait(lambda: re.search(rb"%s (\d+)\r?\n" % marker.encode(), bytes(s.ring)) is not None)
    return int(re.search(rb"%s (\d+)\r?\n" % marker.encode(), bytes(s.ring)).group(1))


def test_job_object_kills_grandchild_started_with_start_b(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "job", str(d), time.time())
    m = TerminalManager(environ={"PATH": __import__("os").environ["PATH"], "SystemRoot": "C:\\Windows",
                                 "COMSPEC": "C:\\Windows\\System32\\cmd.exe"})
    s = m.create(proj, Profile(id="cmd", name="cmd", command="C:\\Windows\\System32\\cmd.exe"))
    gpid = None
    try:
        assert s.handle._job, "job object was not created (check the log for the reason)"
        gpid = _grandchild_pid(m, s, "GCJOB")
        assert _alive(gpid)
    finally:
        m.close(s.id, "test")
    try:
        assert gpid and _wait(lambda: not _alive(gpid), 10), "grandchild survived session close"
    finally:
        if gpid and _alive(gpid):
            subprocess.run(["taskkill", "/F", "/PID", str(gpid)], capture_output=True)


def test_job_creation_failure_is_graceful(monkeypatch):
    assert be._create_kill_on_close_job(None) is None
    assert be._create_kill_on_close_job(0x7FFFFFF0) is None  # no such process: log + fallback, no exception
