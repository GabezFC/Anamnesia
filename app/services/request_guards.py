"""ANA-030 / ANA-033: pure-ASGI request guards (body ceiling before parsing, token-bucket rate limit).

Both are active by default with limits far above normal local use, and both have env rollbacks:
  MG_MAX_BODY_BYTES       default 262144 (256 KiB); 0 = off. Paths ending in /upload or /import get
                          MG_MAX_UPLOAD_BYTES (default 1 MiB). Rejects on Content-Length BEFORE reading the
                          body, and while streaming when no/forged Content-Length: 413.
  MG_RATE_LIMIT_PER_MIN   default 600 req/min per client IP on /memory/search*, /generate, /route,
                          /benchmark/*; 0 = off. 429 + Retry-After. Burst = min(limit, 60).
"""
from __future__ import annotations

import json
import os
import threading
import time

DEFAULT_MAX_BODY = 256 * 1024
DEFAULT_MAX_UPLOAD = 1024 * 1024
DEFAULT_RATE_PER_MIN = 600
RATE_PREFIXES = ("/memory/search", "/generate", "/route", "/benchmark/")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


async def _send_json(send, status: int, detail: str, extra_headers: list | None = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers + (extra_headers or [])})
    await send({"type": "http.response.body", "body": body})


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int | None = None, max_upload: int | None = None):
        self.app = app
        self._max = max_bytes
        self._max_up = max_upload

    def limits(self, path: str) -> int:
        base = self._max if self._max is not None else _env_int("MG_MAX_BODY_BYTES", DEFAULT_MAX_BODY)
        up = self._max_up if self._max_up is not None else _env_int("MG_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD)
        return max(base, up) if (base > 0 and path.rstrip("/").endswith(("/upload", "/import"))) else base

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limits(scope.get("path", ""))
        if limit <= 0:
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers", []):
            if k == b"content-length":
                try:
                    if int(v) > limit:
                        return await _send_json(send, 413, f"corpo maior que {limit} bytes")
                except ValueError:
                    return await _send_json(send, 400, "Content-Length inválido")
        seen = 0
        over = False

        async def counting_receive():
            nonlocal seen, over
            if over:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    over = True   # stop feeding the app; answer 413 ourselves (no exception to be re-wrapped)
                    return {"type": "http.disconnect"}
            return msg

        async def guarded_send(msg):
            if not over:
                await send(msg)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:  # noqa: BLE001 -- an app error caused by our synthetic disconnect
            if not over:
                raise
        if over:
            await _send_json(send, 413, f"corpo maior que {limit} bytes")


class TokenBuckets:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._b: dict[str, tuple[float, float]] = {}  # key -> (tokens, last)

    def take(self, key: str, per_min: int) -> float:
        """0.0 if allowed, else seconds until a token is available."""
        cap = float(min(per_min, 60)) or 1.0
        rate = per_min / 60.0
        now = self._clock()
        with self._lock:
            tokens, last = self._b.get(key, (cap, now))
            tokens = min(cap, tokens + (now - last) * rate)
            if tokens >= 1.0:
                self._b[key] = (tokens - 1.0, now)
                if len(self._b) > 4096:  # bound memory under many distinct clients
                    self._b = dict(sorted(self._b.items(), key=lambda kv: kv[1][1])[-2048:])
                return 0.0
            self._b[key] = (tokens, now)
            return (1.0 - tokens) / rate


class RateLimitMiddleware:
    def __init__(self, app, per_min: int | None = None, clock=time.monotonic):
        self.app = app
        self._per_min = per_min
        self.buckets = TokenBuckets(clock)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(RATE_PREFIXES):
            return await self.app(scope, receive, send)
        per_min = self._per_min if self._per_min is not None else _env_int("MG_RATE_LIMIT_PER_MIN",
                                                                         DEFAULT_RATE_PER_MIN)
        if per_min <= 0:
            return await self.app(scope, receive, send)
        client = scope.get("client")
        wait = self.buckets.take(client[0] if client else "unknown", per_min)
        if wait > 0:
            return await _send_json(send, 429, "limite de requisições excedido",
                                    [(b"retry-after", str(int(wait) + 1).encode())])
        await self.app(scope, receive, send)
