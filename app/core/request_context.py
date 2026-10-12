"""ANA-069: request_id / trace_id / run_id carried in ContextVars.

Every entry point (REST middleware, MCP tool call, CLI, MemoryGateway.search itself) opens a
`request_scope()`; everything below it (jsonl(), metrics_json, jev_batch events, audit rows) reads the
ids from here instead of threading them through signatures. ContextVar = per-request isolation even
though the gateway object is shared (same reasoning as `_active_scope_var` in memory_gateway.py).
"""
from __future__ import annotations

import contextlib
import contextvars
import re
import uuid
from typing import Iterator

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("mg_request_id", default=None)
_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("mg_trace_id", default=None)
_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("mg_run_id", default=None)

# Accepted from a client header (X-Request-ID): short, printable, no log-injection characters.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,63}$")
RUN_ID_HEX_LEN = 20  # ANA-069: >= 16 hex (was 12 = 48 bits)


def new_request_id() -> str:
    return "req-" + uuid.uuid4().hex[:16]


def new_trace_id() -> str:
    return uuid.uuid4().hex  # 32 hex, W3C trace-id shaped


def new_run_id() -> str:
    """Search run id: RUN_ID_HEX_LEN hex chars (80 bits)."""
    return uuid.uuid4().hex[:RUN_ID_HEX_LEN]


def sanitize_id(value: str | None) -> str | None:
    """A client-supplied id is only honoured if it is short and made of safe characters."""
    v = (value or "").strip()
    return v if _SAFE_ID.match(v) else None


def get_request_id() -> str | None:
    return _request_id.get()


def get_trace_id() -> str | None:
    return _trace_id.get()


def get_run_id() -> str | None:
    return _run_id.get()


@contextlib.contextmanager
def request_scope(request_id: str | None = None, trace_id: str | None = None) -> Iterator[str]:
    """Open (or join) a request scope. Nested scopes reuse the outer ids unless explicit ones are given."""
    rid = sanitize_id(request_id) or _request_id.get() or new_request_id()
    tid = sanitize_id(trace_id) or _trace_id.get() or new_trace_id()
    t1, t2 = _request_id.set(rid), _trace_id.set(tid)
    try:
        yield rid
    finally:
        _trace_id.reset(t2)
        _request_id.reset(t1)


@contextlib.contextmanager
def run_scope(run_id: str) -> Iterator[str]:
    tok = _run_id.set(run_id)
    try:
        yield run_id
    finally:
        _run_id.reset(tok)


def context_fields() -> dict[str, str]:
    """Join keys for the current context (only those that are set)."""
    out: dict[str, str] = {}
    for k, v in (("request_id", _request_id.get()), ("trace_id", _trace_id.get()), ("run_id", _run_id.get())):
        if v:
            out[k] = v
    return out
