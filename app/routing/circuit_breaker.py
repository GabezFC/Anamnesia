"""ANA-187: circuit breaker per provider/model.

CLOSED -> (>= `failure_threshold` tripping failures within `window_s`) -> OPEN for `open_s` ->
HALF_OPEN (one probe call allowed at a time) -> success closes it, failure re-opens it.

Only causes that say "this endpoint is unhealthy" trip it: timeout, rate_limit, provider_down, auth,
model_not_found. bad_output / context_overflow / other are about the request, not the endpoint.

Opt-in: `ANAMNESIA_CIRCUIT_BREAKER=1` (default OFF -> the answer loop never consults it). The clock is
injectable; state is a plain dict (`snapshot()` / `restore()`), exposed read-only in GET /api/connections.
In-memory, per process (a restart closes every circuit): documented limit.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable

ENV_FLAG = "ANAMNESIA_CIRCUIT_BREAKER"
TRIPPING_KINDS = frozenset({"timeout", "rate_limit", "provider_down", "auth", "model_not_found"})
CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


def breaker_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def key_for(provider: str | None, model: str | None) -> str:
    return f"{provider or '?'}/{model or '?'}"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, window_s: float = 60.0, open_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic):
        self.failure_threshold, self.window_s, self.open_s, self.clock = failure_threshold, window_s, open_s, clock
        self._lock = threading.Lock()
        self._s: dict[str, dict] = {}

    def _get(self, key: str) -> dict:
        return self._s.setdefault(key, {"state": CLOSED, "failures": [], "opened_at": None, "probing": False,
                                        "last_kind": None, "opens": 0, "rejected": 0})

    def _refresh(self, st: dict) -> None:
        if st["state"] == OPEN and self.clock() - st["opened_at"] >= self.open_s:
            st["state"], st["probing"] = HALF_OPEN, False

    def state(self, key: str) -> str:
        with self._lock:
            st = self._get(key)
            self._refresh(st)
            return st["state"]

    def allow(self, key: str) -> bool:
        """True if a call may go out now. In HALF_OPEN only ONE probe is admitted until it reports back."""
        with self._lock:
            st = self._get(key)
            self._refresh(st)
            if st["state"] == CLOSED:
                return True
            if st["state"] == HALF_OPEN and not st["probing"]:
                st["probing"] = True
                return True
            st["rejected"] += 1
            return False

    def record_success(self, key: str) -> None:
        with self._lock:
            st = self._get(key)
            st.update(state=CLOSED, failures=[], opened_at=None, probing=False)

    def record_failure(self, key: str, kind: str | None) -> None:
        if kind not in TRIPPING_KINDS:
            with self._lock:                       # a non-endpoint failure must not wedge a half-open probe
                self._get(key)["probing"] = False
            return
        with self._lock:
            st = self._get(key)
            self._refresh(st)
            now = self.clock()
            st["last_kind"] = kind
            if st["state"] == HALF_OPEN:
                self._open(st, now)
                return
            st["failures"] = [t for t in st["failures"] if now - t <= self.window_s] + [now]
            if st["state"] == CLOSED and len(st["failures"]) >= self.failure_threshold:
                self._open(st, now)

    @staticmethod
    def _open(st: dict, now: float) -> None:
        st.update(state=OPEN, opened_at=now, probing=False, failures=[])
        st["opens"] += 1

    def snapshot(self) -> dict:
        """JSON-serialisable: {key: {state, recent_failures, retry_in_s, last_kind, opens, rejected}}. No secrets."""
        with self._lock:
            now, out = self.clock(), {}
            for k, st in self._s.items():
                self._refresh(st)
                out[k] = {"state": st["state"],
                          "recent_failures": len([t for t in st["failures"] if now - t <= self.window_s]),
                          "retry_in_s": (round(max(0.0, self.open_s - (now - st["opened_at"])), 3)
                                         if st["state"] == OPEN else 0.0),
                          "last_kind": st["last_kind"], "opens": st["opens"], "rejected": st["rejected"]}
            return out

    def restore(self, snap: dict) -> None:
        """Rebuild from `snapshot()` (timestamps are re-based on the current clock)."""
        with self._lock:
            now = self.clock()
            self._s = {}
            for k, v in (snap or {}).items():
                st = self._get(k)
                st.update(state=v.get("state", CLOSED), last_kind=v.get("last_kind"), opens=v.get("opens", 0),
                          rejected=v.get("rejected", 0))
                st["failures"] = [now] * int(v.get("recent_failures", 0))
                if st["state"] == OPEN:
                    st["opened_at"] = now - (self.open_s - float(v.get("retry_in_s", 0.0)))


_GLOBAL: CircuitBreaker | None = None


def get_breaker() -> CircuitBreaker:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = CircuitBreaker()
    return _GLOBAL


def reset_breaker(new: CircuitBreaker | None = None) -> CircuitBreaker:
    global _GLOBAL
    _GLOBAL = new or CircuitBreaker()
    return _GLOBAL
