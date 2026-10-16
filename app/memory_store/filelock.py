"""ANAM-007: lock de arquivo entre processos (stdlib), reentrante e com timeout.

* Windows: msvcrt.locking (1 byte, não bloqueante + polling); POSIX: fcntl.flock(LOCK_EX | LOCK_NB).
* Reentrante dentro do processo/thread (RLock + contador); threads diferentes se serializam no RLock,
  processos diferentes no lock do SO. O SO libera o lock se o processo morrer.
* Uso: `with FileLock(path): ...` ou como `store._lock` (mesma interface de context manager do RLock).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

try:  # Windows
    import msvcrt as _msvcrt
    _fcntl = None
except ImportError:  # POSIX
    _msvcrt = None
    import fcntl as _fcntl

DEFAULT_TIMEOUT = 30.0


class LockTimeout(TimeoutError):
    pass


class FileLock:
    def __init__(self, path: Path | str, timeout: float = DEFAULT_TIMEOUT, poll: float = 0.005):
        self.path = Path(path)
        self.timeout = timeout
        self.poll = poll
        self._rlock = threading.RLock()
        self._depth = 0
        self._fd: int | None = None

    # -- OS primitives -----------------------------------------------------------------
    def _try_lock(self, fd: int) -> bool:
        try:
            if _msvcrt is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt.locking(fd, _msvcrt.LK_NBLCK, 1)
            else:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(self, fd: int) -> None:
        try:
            if _msvcrt is not None:
                os.lseek(fd, 0, os.SEEK_SET)
                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
            else:
                _fcntl.flock(fd, _fcntl.LOCK_UN)
        except OSError:
            pass

    # -- API ---------------------------------------------------------------------------
    def acquire(self, timeout: float | None = None) -> bool:
        limit = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        if not self._rlock.acquire(timeout=max(limit, 0)):
            raise LockTimeout(f"timeout ({limit}s) aguardando lock em {self.path}")
        try:
            if self._depth > 0:  # reentrante
                self._depth += 1
                return True
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                delay = self.poll
                while not self._try_lock(fd):
                    if time.monotonic() >= deadline:
                        raise LockTimeout(f"timeout ({limit}s) aguardando lock em {self.path}")
                    time.sleep(delay)
                    delay = min(delay * 1.5, 0.05)
            except BaseException:
                os.close(fd)
                raise
            self._fd = fd
            self._depth = 1
            return True
        except BaseException:
            self._rlock.release()
            raise

    def release(self) -> None:
        if self._depth <= 0:
            raise RuntimeError("release de lock não adquirido")
        self._depth -= 1
        try:
            if self._depth == 0 and self._fd is not None:
                fd, self._fd = self._fd, None
                self._unlock(fd)
                os.close(fd)
        finally:
            self._rlock.release()

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def replace_with_retry(src, dst, *, attempts: int = 12, base_delay: float = 0.005, replace=os.replace) -> None:
    """os.replace com retry curto em PermissionError (WinError 5/32: destino aberto por outro processo)."""
    delay = base_delay
    for i in range(attempts):
        try:
            replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)
