"""Phase 10 groundwork: the stdlib `pty` backend works on Linux/macOS (skipped on Windows, where
the backend is pywinpty; see the PTY spike). Real child process, no network, no agent CLI."""
from __future__ import annotations

import os
import select
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty only; Windows uses ConPTY")

if sys.platform != "win32":
    import fcntl
    import pty
    import signal
    import struct
    import termios


def _read_until(fd: int, needle: bytes, timeout: float = 10.0) -> bytes:
    buf = b""
    end = time.time() + timeout
    while time.time() < end and needle not in buf:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
    return buf


def _set_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def test_pty_round_trip():
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("sh", ["sh", "-c", "echo ready; read x; echo got:$x"])
    try:
        assert b"ready" in _read_until(fd, b"ready")
        os.write(fd, b"ping\n")
        assert b"got:ping" in _read_until(fd, b"got:ping")
    finally:
        os.close(fd)
        os.waitpid(pid, 0)


def test_pty_resize_is_seen_by_child():
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("sh", ["sh", "-c", "read a; stty size; read b; stty size"])
    try:
        _set_size(fd, 24, 80)
        os.write(fd, b"\n")
        assert b"24 80" in _read_until(fd, b"24 80")
        _set_size(fd, 30, 120)
        os.write(fd, b"\n")
        assert b"30 120" in _read_until(fd, b"30 120")
    finally:
        os.close(fd)
        os.waitpid(pid, 0)


def test_closing_pty_and_killing_group_leaves_no_orphan():
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp("sh", ["sh", "-c", "sleep 300 & echo child:$!; wait"])
    out = _read_until(fd, b"child:")
    grandchild = int(out.split(b"child:")[1].split()[0])
    os.kill(grandchild, 0)  # alive before
    os.close(fd)
    os.killpg(os.getpgid(pid), signal.SIGKILL)
    os.waitpid(pid, 0)
    time.sleep(0.5)
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild, 0)
