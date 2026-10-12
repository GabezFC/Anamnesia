"""ANA-032 (slice): per-terminal-session token whose scope is fixed SERVER-side.

A terminal session gets `MG_SESSION_TOKEN` (random, in-memory only, revoked when the session closes).
A REST caller that presents it in `X-MG-Session` on /memory/search* or /generate has its client-sent
`scope` IGNORED and replaced by the scope bound to the token (the project the terminal was opened on).
Soft isolation only: a process of the same OS user can still read `.env`; this narrows what an agent
running inside the PTY can ask the HTTP API for. Hard isolation needs a separate user/container.
"""
from __future__ import annotations

import secrets
import threading
import time

HEADER = "x-mg-session"
ENV_VAR = "MG_SESSION_TOKEN"
DEFAULT_TTL_S = 24 * 3600.0

_lock = threading.Lock()
_tokens: dict[str, tuple[str, float]] = {}  # token -> (scope label, expires_at)


def mint(scope: str, ttl_s: float = DEFAULT_TTL_S) -> str:
    """New token bound to `scope` (e.g. 'projeto:alpha' or a bare project name)."""
    token = "mgs_" + secrets.token_urlsafe(24)
    with _lock:
        _tokens[token] = (scope, time.time() + ttl_s)
    return token


def resolve(token: str | None) -> str | None:
    """Scope bound to `token`, or None if unknown/expired/revoked."""
    if not token:
        return None
    with _lock:
        hit = None
        for known, val in _tokens.items():  # constant-ish time compare against every stored token
            if secrets.compare_digest(known, token):
                hit = val
        if hit is None:
            return None
        if hit[1] < time.time():
            _tokens.pop(token, None)
            return None
        return hit[0]


def revoke(token: str | None) -> None:
    if token:
        with _lock:
            _tokens.pop(token, None)


def clear() -> None:
    with _lock:
        _tokens.clear()
