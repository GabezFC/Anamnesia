"""Terminal tree kill, Job Object (Windows) / killpg (POSIX), Ctrl+C to a real child, janitor, with REAL processes.

Inclui (ex-test_terminals_jobobject.py, fundido) o Job Object KILL_ON_JOB_CLOSE com sessao pywinpty real:
neto `start /b` morre ao fechar a sessao; falha de criacao do job e graciosa. Somente Windows + pywinpty."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

import pytest

from app.terminals import backend as be
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import Project

WIN = sys.platform == "win32"


def _have_backend() -> bool:
    if WIN:
        try:
            import winpty  # noqa: F401
            return True
        except ImportError:
            return False
    return True


pytestmark = pytest.mark.skipif(not _have_backend(), reason="needs a real PTY backend (pywinpty on Windows)")


def alive(pid: int) -> bool:
    if WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True).stdout.decode("latin-1")
        return f" {pid} " in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # zombie counts as dead
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def _env():
    keep = ("PATH", "SystemRoot", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME")
    return {k: os.environ[k] for k in keep if k in os.environ}


def _enable_ctrl_c():
    """A parent started in the background (CI, bash &) may have Ctrl+C disabled, and children inherit that."""
    if WIN:
        import ctypes
        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)


@pytest.fixture
def mgr(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    _enable_ctrl_c()
    m = TerminalManager(environ=_env())
    yield m, Project("p1", "p", str(d), time.time())
    m.close_all()


# child: prints its pid, spawns a grandchild python sleeper, prints both pids, then sleeps
TREE = """
import subprocess, sys, time, os
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
print("CH", os.getpid(), "GR", g.pid, flush=True)
time.sleep(300)
"""


def _py_profile(code: str) -> Profile:
    """Run `code` from a script file (avoids Windows command-line quoting of -c)."""
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    f.write(code)
    f.close()
    return Profile(id="py", name="py", command=sys.executable, args=(f.name,))


def _pids(s, tag: bytes, n: int):
    assert wait(lambda: re.search(tag + rb" (\d+) GR (\d+)", bytes(s.ring)) is not None), bytes(s.ring)
    m = re.search(tag + rb" (\d+) GR (\d+)", bytes(s.ring))
    return int(m.group(1)), int(m.group(2))


def test_close_kills_whole_descendant_tree(mgr):
    m, proj = mgr
    s = m.create(proj, _py_profile(TREE))
    child, grand = _pids(s, b"CH", 2)
    assert alive(child) and alive(grand)
    m.close(s.id, "test")
    assert wait(lambda: not alive(child) and not alive(grand)), "descendants survived close()"


@pytest.mark.skipif(not WIN, reason="Job Object is Windows only")
def test_job_object_created_and_kill_on_close_flag(mgr):
    m, proj = mgr
    s = m.create(proj, _py_profile("import time;time.sleep(300)"))
    assert s.handle._job, "job object missing"
    pid = s.handle.pid
    m.close(s.id, "test")
    assert wait(lambda: not alive(pid))
    assert s.handle._job is None  # handle closed => KILL_ON_JOB_CLOSE fired


@pytest.mark.skipif(WIN, reason="POSIX no-op check")
def test_posix_job_helper_is_noop():
    assert be._create_kill_on_close_job(os.getpid()) is None


def test_job_helper_noop_for_bad_pid():
    assert be._create_kill_on_close_job(None) is None
    assert be._create_kill_on_close_job(0) is None
    assert be._create_kill_on_close_job(0x7FFFFFF0) is None


def test_ctrl_c_reaches_real_child_and_session_survives(mgr):
    m, proj = mgr
    code = ("import time\n"
            "try:\n print('READY',flush=True);time.sleep(300)\n"
            "except KeyboardInterrupt:\n print('GOT_SIGINT',flush=True);time.sleep(300)\n")
    s = m.create(proj, _py_profile(code))
    assert wait(lambda: b"READY" in bytes(s.ring))
    m.write(s.id, b"\x03")
    assert wait(lambda: b"GOT_SIGINT" in bytes(s.ring)), bytes(s.ring)
    assert s.state == "active" and s.handle.isalive()


def test_janitor_expires_idle_real_session_and_tree(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    _enable_ctrl_c()
    m = TerminalManager(environ=_env(), idle_seconds=6, janitor_interval=0.2)
    try:
        s = m.create(proj, _py_profile(TREE))
        child, grand = _pids(s, b"CH", 2)
        assert wait(lambda: s.id not in {x.id for x in m.list()}, 30), "janitor did not reap"
        assert wait(lambda: not alive(child) and not alive(grand))
    finally:
        m.close_all()
    assert m._janitor is None  # janitor is stoppable


# ------------------------------------------------------------------ fundido de test_terminals_jobobject.py
_WIN_ONLY = pytest.mark.skipif(not (WIN and _have_backend()), reason="needs Windows + pywinpty")
_WIN_MARK = pytest.mark.windows_only          # arquivo misto: o marcador e por teste, nao por arquivo


def _grandchild_pid(m, s, marker: str) -> int:
    """Start `cmd /c start /b python -c <sleep>` from the session shell; return the sleeper's PID."""
    py = sys.executable
    m.write(s.id, f'cmd /c start /b "" "{py}" -c "import os,time;print(\'{marker}\',os.getpid(),flush=True);'
                  f'time.sleep(300)"\r\n')
    assert wait(lambda: re.search(rb"%s (\d+)\r?\n" % marker.encode(), bytes(s.ring)) is not None)
    return int(re.search(rb"%s (\d+)\r?\n" % marker.encode(), bytes(s.ring)).group(1))


@_WIN_ONLY
@_WIN_MARK
def test_job_object_kills_grandchild_started_with_start_b(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "job", str(d), time.time())
    m = TerminalManager(environ={"PATH": os.environ["PATH"], "SystemRoot": "C:\\Windows",
                                 "COMSPEC": "C:\\Windows\\System32\\cmd.exe"})
    s = m.create(proj, Profile(id="cmd", name="cmd", command="C:\\Windows\\System32\\cmd.exe"))
    gpid = None
    try:
        assert s.handle._job, "job object was not created (check the log for the reason)"
        gpid = _grandchild_pid(m, s, "GCJOB")
        assert alive(gpid)
    finally:
        m.close(s.id, "test")
    try:
        assert gpid and wait(lambda: not alive(gpid), 10), "grandchild survived session close"
    finally:
        if gpid and alive(gpid):
            subprocess.run(["taskkill", "/F", "/PID", str(gpid)], capture_output=True)


@_WIN_ONLY
@_WIN_MARK
def test_job_creation_failure_is_graceful(monkeypatch):
    assert be._create_kill_on_close_job(None) is None
    assert be._create_kill_on_close_job(0x7FFFFFF0) is None  # no such process: log + fallback, no exception
