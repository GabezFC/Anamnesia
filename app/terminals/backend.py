"""PTY backends behind one tiny interface.

`PtyBackend.spawn(...)` returns a `PtyHandle`:
  read()            blocking; returns bytes (>0 length) or raises EOFError when the child side is gone
  write(data)       bytes to the child's stdin
  resize(rows, cols)
  isalive()
  exit_code         int | None (best effort)
  terminate_tree()  kill the child AND its descendants, idempotent

Heavy/OS-specific modules (winpty, pty, fcntl, termios) are imported lazily so that importing this
module works on every OS and without the optional `terminal` extra.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from typing import Protocol, runtime_checkable


class BackendUnavailable(RuntimeError):
    """The PTY backend for this OS cannot be used (e.g. pywinpty not installed)."""


@runtime_checkable
class PtyHandle(Protocol):
    pid: int | None
    exit_code: int | None

    def read(self) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    def resize(self, rows: int, cols: int) -> None: ...
    def isalive(self) -> bool: ...
    def terminate_tree(self) -> None: ...


class PtyBackend(Protocol):
    name: str

    def spawn(self, argv: list[str], cwd: str, env: dict[str, str], rows: int, cols: int) -> PtyHandle: ...


# ------------------------------------------------------------------ Windows (pywinpty / ConPTY)
class _WinPtyHandle:
    def __init__(self, proc):
        self._p = proc
        self.pid = getattr(proc, "pid", None)
        self._closed = False

    @property
    def exit_code(self) -> int | None:
        try:
            return getattr(self._p, "exitstatus", None)
        except Exception:
            return None

    def read(self) -> bytes:
        while True:
            try:
                s = self._p.read(65536)
            except EOFError:
                raise
            except Exception as e:  # handle closed under us / broken pipe -> treat as EOF
                raise EOFError(str(e)) from e
            if s:
                return s.encode("utf-8", "replace") if isinstance(s, str) else bytes(s)
            if not self._p.isalive():
                raise EOFError("child exited")
            threading.Event().wait(0.01)  # empty read on a live child: avoid a hot loop

    def write(self, data: bytes) -> None:
        self._p.write(data.decode("utf-8", "replace"))

    def resize(self, rows: int, cols: int) -> None:
        self._p.setwinsize(int(rows), int(cols))

    def isalive(self) -> bool:
        try:
            return bool(self._p.isalive())
        except Exception:
            return False

    def terminate_tree(self) -> None:
        if self._closed:
            return
        self._closed = True
        pid = self.pid
        # taskkill first, while the root process is still alive (its PID cannot be recycled yet)
        # and /T can still walk the tree; then close the ConPTY.
        if pid:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True,
                               timeout=10, check=False)
            except Exception:
                pass
        try:
            self._p.close(force=True)
        except Exception:
            pass


class WinPtyBackend:
    name = "winpty"

    def spawn(self, argv, cwd, env, rows, cols) -> PtyHandle:
        try:
            from winpty import PtyProcess  # lazy: optional extra `terminal`
        except ImportError as e:
            raise BackendUnavailable("pywinpty não instalado (pip install 'anamnesia[terminal]')") from e
        proc = PtyProcess.spawn(list(argv), cwd=cwd, env=dict(env), dimensions=(int(rows), int(cols)))
        return _WinPtyHandle(proc)


# ------------------------------------------------------------------ POSIX (stdlib pty)
class _PosixPtyHandle:
    def __init__(self, pid: int, fd: int):
        self.pid = pid
        self._fd = fd
        self.exit_code: int | None = None
        self._closed = False
        self._lock = threading.Lock()

    def read(self) -> bytes:
        import select

        while True:
            if self._closed:
                raise EOFError("closed")
            try:
                r, _, _ = select.select([self._fd], [], [], 0.2)
            except (OSError, ValueError) as e:
                raise EOFError(str(e)) from e
            if not r:
                continue
            try:
                data = os.read(self._fd, 65536)
            except OSError as e:  # EIO on Linux when the slave side closed
                raise EOFError(str(e)) from e
            if not data:
                raise EOFError("eof")
            return data

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            n = os.write(self._fd, view)
            view = view[n:]

    def resize(self, rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios

        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))

    def _reap(self, block: bool) -> bool:
        if self.exit_code is not None:
            return True
        try:
            pid, status = os.waitpid(self.pid, 0 if block else os.WNOHANG)
        except ChildProcessError:
            self.exit_code = self.exit_code if self.exit_code is not None else -1
            return True
        if pid == 0:
            return False
        self.exit_code = os.waitstatus_to_exitcode(status)
        return True

    def isalive(self) -> bool:
        with self._lock:
            return not self._reap(False)

    def _snapshot_tree(self) -> set[int]:
        """PIDs belonging to this session: the descendants of the leader, plus (Linux) every process
        whose session id is the leader's. Interactive shells run background jobs in their OWN process
        group, so killpg(leader) alone misses them (reproduced on Linux CI)."""
        pids: set[int] = set()
        edges: dict[int, list[int]] = {}
        sids: dict[int, int] = {}
        if os.path.isdir("/proc"):
            for name in os.listdir("/proc"):
                if not name.isdigit():
                    continue
                try:
                    with open(f"/proc/{name}/stat") as f:
                        rest = f.read().rsplit(")", 1)[1].split()
                    ppid, sid = int(rest[1]), int(rest[3])
                except (OSError, ValueError, IndexError):
                    continue
                edges.setdefault(ppid, []).append(int(name))
                sids[int(name)] = sid
        else:  # macOS and other POSIX without /proc
            import subprocess

            try:
                out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True,
                                     timeout=5).stdout
            except (OSError, subprocess.SubprocessError):
                out = ""
            for line in out.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    edges.setdefault(int(parts[1]), []).append(int(parts[0]))
        stack = [self.pid]
        while stack:
            cur = stack.pop()
            for child in edges.get(cur, ()):
                if child not in pids:
                    pids.add(child)
                    stack.append(child)
        pids.update(p for p, s in sids.items() if s == self.pid)
        pids.discard(self.pid)
        pids.discard(os.getpid())
        return pids

    def terminate_tree(self) -> None:
        import signal
        import time

        with self._lock:
            if self._closed:
                return
            self._closed = True
            stragglers = self._snapshot_tree()  # taken BEFORE killing: orphans lose their lineage
            for sig in (signal.SIGHUP, signal.SIGKILL):
                try:
                    os.killpg(self.pid, sig)  # child is a session leader => pgid == pid
                except (ProcessLookupError, PermissionError):
                    pass
                end = time.time() + (1.0 if sig == signal.SIGHUP else 3.0)
                while time.time() < end:
                    if self._reap(False):
                        break
                    time.sleep(0.02)
                # No early exit after SIGHUP: the session leader may exit on hangup while a
                # background job in the same group survives (reproduced on Linux). The group
                # always gets the final SIGKILL, which is harmless when it is already empty.
            for pid in stragglers:  # background jobs in their own process group / session members
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            try:
                os.close(self._fd)
            except OSError:
                pass


class PosixPtyBackend:
    name = "posix-pty"

    def spawn(self, argv, cwd, env, rows, cols) -> PtyHandle:
        import fcntl  # noqa: F401  (lazy POSIX-only imports; ImportError on Windows)
        import pty
        import struct
        import termios

        pid, fd = pty.fork()
        if pid == 0:  # child
            try:
                os.chdir(cwd)
                os.execvpe(argv[0], list(argv), dict(env))
            except BaseException:
                os._exit(127)
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", int(rows), int(cols), 0, 0))
        except OSError:
            pass
        return _PosixPtyHandle(pid, fd)


# ------------------------------------------------------------------ Fake (tests)
class FakePtyHandle:
    """In-memory PTY: echoes whatever is written (unless echo=False). Records everything."""

    _next_pid = 10_000

    def __init__(self, argv, cwd, env, rows, cols, echo: bool = True):
        FakePtyHandle._next_pid += 1
        self.pid: int | None = FakePtyHandle._next_pid
        self.exit_code: int | None = None
        self.argv, self.cwd, self.env = list(argv), cwd, dict(env)
        self.rows, self.cols = rows, cols
        self.echo = echo
        self.written: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.terminated = 0
        self._q: queue.Queue[bytes | None] = queue.Queue()
        self._alive = True

    # test helpers
    def emit(self, data: bytes) -> None:
        self._q.put(data)

    def finish(self, code: int = 0) -> None:
        self.exit_code = code
        self._alive = False
        self._q.put(None)

    # PtyHandle
    def read(self) -> bytes:
        item = self._q.get()
        if item is None:
            self._q.put(None)  # stay at EOF for repeated reads
            raise EOFError("fake eof")
        return item

    def write(self, data: bytes) -> None:
        self.written.append(bytes(data))
        if self.echo and self._alive:
            self._q.put(bytes(data))

    def resize(self, rows: int, cols: int) -> None:
        self.rows, self.cols = rows, cols
        self.resizes.append((rows, cols))

    def isalive(self) -> bool:
        return self._alive

    def terminate_tree(self) -> None:
        self.terminated += 1
        if self._alive:
            self.finish(-1 if self.exit_code is None else self.exit_code)


class FakePtyBackend:
    name = "fake"

    def __init__(self, echo: bool = True):
        self.echo = echo
        self.spawned: list[FakePtyHandle] = []

    def spawn(self, argv, cwd, env, rows, cols) -> FakePtyHandle:
        h = FakePtyHandle(argv, cwd, env, rows, cols, echo=self.echo)
        self.spawned.append(h)
        return h


def default_backend() -> PtyBackend:
    return WinPtyBackend() if sys.platform == "win32" else PosixPtyBackend()
