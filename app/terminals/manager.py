"""TerminalManager: sessions (one PTY + one reader thread each), ring buffer replay, limits, expiry.

Thread-safe and asyncio-agnostic: reader threads push output to subscribers through
`loop.call_soon_threadsafe` (the pattern validated in the PTY spike).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.terminals.backend import PtyBackend, PtyHandle, default_backend

audit = logging.getLogger("anamnesia.terminals.audit")
log = logging.getLogger("anamnesia.terminals")

DEFAULT_MAX_SESSIONS = 8
DEFAULT_RING_BYTES = 1024 * 1024
DEFAULT_IDLE_SECONDS = 12 * 3600
SUBSCRIBER_QUEUE_LIMIT = 4096
DEFAULT_JANITOR_SECONDS = 60.0

# Fixed allowlist (matched case-insensitively: Windows env names are case-insensitive).
ENV_ALLOWLIST = ("PATH", "HOME", "USERPROFILE", "LANG", "TERM", "SystemRoot", "COMSPEC", "TEMP",
                 "TMP", "PATHEXT")


class SessionLimitError(RuntimeError):
    pass


class SessionNotFound(KeyError):
    pass


def build_env(env_keys=(), environ=None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Allowlisted environment + ONLY the keys the chosen profile declares (never the whole env)."""
    src = os.environ if environ is None else environ
    upper = {k.upper(): k for k in src}
    out: dict[str, str] = {}
    for key in (*ENV_ALLOWLIST, *env_keys):
        real = upper.get(key.upper())
        if real is not None and src[real] != "":
            out[real if sys.platform == "win32" else key] = src[real]
    if not any(k.upper() == "TERM" for k in out):
        out["TERM"] = "xterm-256color"
    out.update(extra or {})
    return out


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, ""))
        return v if v > 0 else default
    except ValueError:
        return default


class Subscriber:
    """Bridge from a reader thread to one asyncio consumer (a WebSocket)."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue | None = None):
        self.loop = loop
        self.queue: asyncio.Queue = queue or asyncio.Queue()
        self.dead = False

    def _push(self, item: bytes | None) -> None:
        if self.queue.qsize() > SUBSCRIBER_QUEUE_LIMIT:  # slow client: drop it, session lives on
            self.dead = True
            item = None
        self.queue.put_nowait(item)

    def deliver(self, item: bytes | None) -> bool:
        if self.dead:
            return False
        try:
            self.loop.call_soon_threadsafe(self._push, item)
            return True
        except RuntimeError:  # loop closed
            self.dead = True
            return False


@dataclass
class Session:
    id: str
    project_id: str
    project_path: str
    profile_id: str
    handle: PtyHandle
    rows: int
    cols: int
    started_at: float
    state: str = "active"  # active | ended
    ended_at: float | None = None
    exit_code: int | None = None
    ring: bytearray = field(default_factory=bytearray, repr=False)
    subscribers: list[Subscriber] = field(default_factory=list, repr=False)
    last_client_at: float = 0.0  # monotonic; refreshed on attach/detach/creation
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    thread: threading.Thread | None = field(default=None, repr=False)
    close_reason: str | None = None
    worktree_id: str | None = None

    @property
    def pid(self) -> int | None:
        return self.handle.pid

    def to_dict(self) -> dict:
        return {"id": self.id, "project_id": self.project_id, "profile_id": self.profile_id,
                "state": self.state, "pid": self.pid, "rows": self.rows, "cols": self.cols,
                "started_at": self.started_at, "ended_at": self.ended_at, "exit_code": self.exit_code,
                "clients": len(self.subscribers), "worktree_id": self.worktree_id,
                "cwd": self.project_path}


class TerminalManager:
    def __init__(self, backend: PtyBackend | None = None, max_sessions: int | None = None,
                 ring_bytes: int | None = None, idle_seconds: float | None = None,
                 clock=time.monotonic, environ=None, janitor_interval: float = DEFAULT_JANITOR_SECONDS):
        self.backend = backend or default_backend()
        self.max_sessions = max_sessions or _env_int("ANAMNESIA_MAX_SESSIONS", DEFAULT_MAX_SESSIONS)
        self.ring_bytes = ring_bytes or DEFAULT_RING_BYTES
        self.idle_seconds = idle_seconds if idle_seconds is not None else DEFAULT_IDLE_SECONDS
        self._clock = clock
        self._environ = environ  # None => os.environ at create() time
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self.janitor_interval = janitor_interval
        self._janitor: threading.Thread | None = None
        self._janitor_stop = threading.Event()

    # ------------------------------------------------------------ janitor
    def _ensure_janitor(self) -> None:
        with self._lock:
            if self._janitor is not None and self._janitor.is_alive():
                return
            self._janitor_stop = stop = threading.Event()
            self._janitor = threading.Thread(target=self._janitor_loop, args=(stop,),
                                             name="pty-janitor", daemon=True)
            self._janitor.start()

    def _janitor_loop(self, stop: threading.Event) -> None:
        while not stop.wait(self.janitor_interval):
            try:
                gone = self.reap()
                if gone:
                    audit.info("janitor_reaped count=%d", len(gone))
            except Exception:
                log.exception("janitor tick failed")

    def _stop_janitor(self) -> None:
        with self._lock:
            t, self._janitor = self._janitor, None
            self._janitor_stop.set()
        if t is not None and t is not threading.current_thread():
            t.join(timeout=5)

    # ------------------------------------------------------------ lifecycle
    def create(self, project, profile, cols: int = 80, rows: int = 24, cwd: str | None = None,
               worktree_id: str | None = None) -> Session:
        """`project`: object with id/name/path. `profile`: app.terminals.profiles.Profile.
        `cwd` overrides the project path (used for git worktrees; the caller validated it)."""
        self.reap()
        cols, rows = self._clamp(cols, 80), self._clamp(rows, 24)
        cwd = os.path.realpath(cwd or project.path)
        if not os.path.isdir(cwd):
            raise FileNotFoundError("diretório do projeto não existe mais")
        argv = profile.argv()
        env = build_env(profile.env_keys, self._environ, {"MG_SCOPE": project.name})
        with self._lock:
            active = sum(1 for s in self._sessions.values() if s.state == "active")
            if active >= self.max_sessions:
                raise SessionLimitError(f"limite de {self.max_sessions} sessões simultâneas atingido")
            handle = self.backend.spawn(argv, cwd, env, rows, cols)
            s = Session(uuid.uuid4().hex[:12], project.id, cwd, profile.id, handle, rows, cols,
                        time.time(), last_client_at=self._clock(), worktree_id=worktree_id)
            self._sessions[s.id] = s
        self._ensure_janitor()
        t = threading.Thread(target=self._pump, args=(s,), name=f"pty-reader-{s.id}", daemon=True)
        s.thread = t
        t.start()
        audit.info("session_open id=%s project=%s profile=%s pid=%s", s.id, project.id, profile.id, s.pid)
        return s

    @staticmethod
    def _clamp(v, default: int) -> int:
        try:
            return max(1, min(500, int(v)))
        except (TypeError, ValueError):
            return default

    def _pump(self, s: Session) -> None:
        try:
            while True:
                data = s.handle.read()
                with s.lock:
                    s.ring += data
                    over = len(s.ring) - self.ring_bytes
                    if over > 0:
                        del s.ring[:over]
                    subs = list(s.subscribers)
                for sub in subs:
                    sub.deliver(data)
        except (EOFError, OSError):
            pass
        except Exception:  # never let a reader thread die noisily
            log.exception("reader thread failed for session %s", s.id)
        self._mark_ended(s, "process_exited")

    def _mark_ended(self, s: Session, reason: str) -> None:
        with s.lock:
            if s.state == "ended":
                return
            s.state = "ended"
            s.ended_at = time.time()
            s.close_reason = reason
            try:
                s.exit_code = s.handle.exit_code
            except Exception:
                s.exit_code = None
            subs = list(s.subscribers)
        for sub in subs:
            sub.deliver(None)
        audit.info("session_close id=%s reason=%s code=%s", s.id, reason, s.exit_code)

    def close(self, session_id: str, reason: str = "user", remove: bool = True) -> bool:
        with self._lock:
            s = self._sessions.get(session_id)
        if s is None:
            return False
        try:
            s.handle.terminate_tree()
        except Exception:
            log.exception("terminate_tree failed for %s", session_id)
        self._mark_ended(s, reason)
        if s.thread and s.thread is not threading.current_thread():
            s.thread.join(timeout=5)
        if remove:
            with self._lock:
                self._sessions.pop(session_id, None)
        return True

    def close_all(self, reason: str = "shutdown") -> None:
        self._stop_janitor()
        for sid in list(self._sessions):
            self.close(sid, reason)

    def reap(self, now: float | None = None) -> list[str]:
        """Expire sessions without clients for longer than idle_seconds (active ones are killed;
        ended ones are dropped from the table after the same delay)."""
        now = self._clock() if now is None else now
        with self._lock:
            victims = [s for s in self._sessions.values()
                       if not s.subscribers and now - s.last_client_at > self.idle_seconds]
        gone = []
        for s in victims:
            self.close(s.id, "expired" if s.state == "active" else "expired_ended")
            gone.append(s.id)
        return gone

    # ------------------------------------------------------------ access
    def get(self, session_id: str) -> Session:
        with self._lock:
            s = self._sessions.get(session_id)
        if s is None:
            raise SessionNotFound(session_id)
        return s

    def list(self) -> list[Session]:
        self.reap()
        with self._lock:
            return sorted(self._sessions.values(), key=lambda s: s.started_at)

    def write(self, session_id: str, data: bytes | str) -> None:
        s = self.get(session_id)
        if s.state != "active":
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            s.handle.write(data)
        except (OSError, EOFError):
            pass  # child gone; the reader thread will mark the session ended

    def resize(self, session_id: str, rows: int, cols: int) -> None:
        s = self.get(session_id)
        rows, cols = self._clamp(rows, s.rows), self._clamp(cols, s.cols)
        if s.state == "active":
            try:
                s.handle.resize(rows, cols)
            except (OSError, EOFError):
                return
        s.rows, s.cols = rows, cols

    # ------------------------------------------------------------ clients
    def subscribe(self, session_id: str, loop: asyncio.AbstractEventLoop) -> tuple[Subscriber, bytes]:
        """Atomically snapshot the replay buffer and register for live output (no gap, no dup)."""
        s = self.get(session_id)
        sub = Subscriber(loop)
        with s.lock:
            replay = bytes(s.ring)
            s.subscribers.append(sub)
            ended = s.state == "ended"
        s.last_client_at = self._clock()
        if ended:
            sub.deliver(None)
        return sub, replay

    def unsubscribe(self, session_id: str, sub: Subscriber) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
        if s is None:
            return
        with s.lock:
            if sub in s.subscribers:
                s.subscribers.remove(sub)
        s.last_client_at = self._clock()
