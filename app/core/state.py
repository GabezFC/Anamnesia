"""Process-wide application state, injected instead of read from `routes._state` (ANA-106).

* `AppState.gateway` -- the single shared MemoryGateway (set by app.main's lifespan).
* `JobStore` -- benchmark jobs with a TTL on finished ones (they used to grow forever in a dict).
* `STATE` is the default instance; FastAPI endpoints receive it through `Depends(get_gateway)`
  (app/api/deps.py), so tests override `app.dependency_overrides[get_gateway]` or build their own
  `AppState` instead of monkeypatching a module-level dict.
"""
from __future__ import annotations

import threading
import time
from collections.abc import MutableMapping
from typing import Any, Callable


class JobStore:
    """Thread-safe job registry. Finished jobs (done/error) expire `ttl_s` seconds after they end."""

    def __init__(self, ttl_s: float = 3600.0, clock: Callable[[], float] = time.monotonic):
        self.ttl_s = ttl_s
        self._clock = clock
        self._jobs: dict[str, dict] = {}
        self._ended: dict[str, float] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self._clock()
        for jid in [j for j, t in self._ended.items() if now - t > self.ttl_s]:
            self._jobs.pop(jid, None)
            self._ended.pop(jid, None)

    def create(self, job_id: str, **fields: Any) -> dict:
        with self._lock:
            self._purge()
            job = {"status": "running", "progress": [], **fields}
            self._jobs[job_id] = job
            return job

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.update(fields)
            if job.get("status") in ("done", "error"):
                self._ended[job_id] = self._clock()

    def append_progress(self, job_id: str, event: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job["progress"].append(event)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            self._purge()
            return self._jobs.get(job_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)


class GatewayNotReady(RuntimeError):
    """No gateway has been installed yet (API maps this to HTTP 503)."""


class AppState:
    def __init__(self, gateway: Any = None, jobs: JobStore | None = None):
        self.gateway = gateway
        self.jobs = jobs or JobStore()

    def require_gateway(self) -> Any:
        if self.gateway is None:
            raise GatewayNotReady("gateway não inicializado")
        return self.gateway


STATE = AppState()


class LegacyStateView(MutableMapping):
    """Dict facade over an AppState for old callers (`routes.<legacy>["gateway"]`). Deprecated."""

    _KEYS = ("gateway", "jobs")

    def __init__(self, state: AppState):
        self._s = state

    def __getitem__(self, k):
        if k not in self._KEYS:
            raise KeyError(k)
        return getattr(self._s, k)

    def __setitem__(self, k, v):
        if k not in self._KEYS:
            raise KeyError(k)
        setattr(self._s, k, v)

    def __delitem__(self, k):
        raise TypeError("cannot delete state keys")

    def __iter__(self):
        return iter(self._KEYS)

    def __len__(self):
        return len(self._KEYS)
