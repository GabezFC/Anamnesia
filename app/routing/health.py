"""ANA-190: cheap, honest provider health.

`healthy` here is NOT "an API key is present". It combines
  * the outcome of the last N REAL calls per model (error rate, p50/p95 latency), recorded by the answer
    loop when `ANAMNESIA_HEALTH=1` (default OFF; in-memory, per process), and
  * an optional light probe, opt-in: Ollama `GET /api/tags` with `ANAMNESIA_HEALTH_PROBE=1`; a cloud
    `list_models()` ONLY with `ANAMNESIA_ALLOW_NETWORK_TEST=1` (both off -> `{"skipped": ...}`, no I/O).
Verdicts: unknown (< MIN_SAMPLES real calls) | healthy | degraded | unhealthy. Probes never send a prompt,
so they cost no tokens. No secrets, prompts or response bodies are stored: only ok/kind/latency numbers.
"""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from typing import Any, Callable

ENV_FLAG = "ANAMNESIA_HEALTH"
PROBE_FLAG = "ANAMNESIA_HEALTH_PROBE"
NETWORK_FLAG = "ANAMNESIA_ALLOW_NETWORK_TEST"
WINDOW = 50
MIN_SAMPLES = 3


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def health_enabled() -> bool:
    return _on(ENV_FLAG)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    return s[max(0, min(len(s) - 1, math.ceil(p / 100.0 * len(s)) - 1))]


class HealthTracker:
    def __init__(self, window: int = WINDOW, clock: Callable[[], float] = time.time):
        self.window, self.clock = window, clock
        self._lock = threading.Lock()
        self._d: dict[str, deque] = {}

    def record(self, key: str, ok: bool, latency_ms: float | None = None, kind: str | None = None) -> None:
        with self._lock:
            self._d.setdefault(key, deque(maxlen=self.window)).append(
                (bool(ok), None if latency_ms is None else float(latency_ms), kind, self.clock()))

    def stats(self, key: str) -> dict[str, Any]:
        with self._lock:
            rows = list(self._d.get(key, ()))
        n = len(rows)
        errs = [r for r in rows if not r[0]]
        lat = [r[1] for r in rows if r[0] and r[1] is not None]
        rate = (len(errs) / n) if n else None
        last_kinds = [r[2] for r in errs]
        st = {"n": n, "errors": len(errs), "error_rate": None if rate is None else round(rate, 4),
              "p50_ms": percentile(lat, 50), "p95_ms": percentile(lat, 95),
              "last_error_kind": last_kinds[-1] if last_kinds else None,
              "last_ts": rows[-1][3] if rows else None}
        st["verdict"] = self.verdict_of(rows)
        return st

    @staticmethod
    def verdict_of(rows: list) -> str:
        n = len(rows)
        if n < MIN_SAMPLES:
            return "unknown"
        rate = sum(1 for r in rows if not r[0]) / n
        if not any(r[0] for r in rows[-MIN_SAMPLES:]) or rate > 0.5:
            return "unhealthy"
        return "degraded" if rate > 0.2 else "healthy"

    def verdict(self, key: str) -> str:
        with self._lock:
            return self.verdict_of(list(self._d.get(key, ())))

    def keys(self) -> list[str]:
        with self._lock:
            return sorted(self._d)

    def all_stats(self) -> dict[str, dict]:
        return {k: self.stats(k) for k in self.keys()}


_GLOBAL: HealthTracker | None = None


def get_tracker() -> HealthTracker:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = HealthTracker()
    return _GLOBAL


def reset_tracker(new: HealthTracker | None = None) -> HealthTracker:
    global _GLOBAL
    _GLOBAL = new or HealthTracker()
    return _GLOBAL


# ------------------------------------------------------------------ probes (opt-in, no tokens)
_PROBE_CACHE: dict = {}
PROBE_TTL_S = 10.0


def probe_ollama(base_url: str = "http://localhost:11434", http_get: Callable | None = None,
                 model: str | None = None) -> dict:
    """ANAM-032 / AUD-093: real Ollama health, no prompt sent. `GET /api/tags` = installed models,
    `GET /api/ps` = models loaded in memory now (docs/api.md). Reports `runtime_running` (server answered),
    `installed`/`models`, `loaded_models` and, if `model` is given, `model_installed`/`model_loaded`.
    A failing /api/ps (older server) leaves loaded_models None (unknown), never a guess. Result cached 10 s
    per (url, model) unless `http_get` is injected (tests)."""
    if not _on(PROBE_FLAG):
        return {"skipped": f"{PROBE_FLAG}!=1"}
    cache_key = (base_url, model)
    use_cache = http_get is None
    if http_get is None:
        hit = _PROBE_CACHE.get(cache_key)
        if hit and time.monotonic() - hit[0] < PROBE_TTL_S:
            return dict(hit[1])
        import httpx
        http_get = httpx.get
    t0 = time.perf_counter()
    try:
        from app.services.egress import check_egress  # ANAM-005
        check_egress(base_url, "health_probe_ollama")
        root = base_url.rstrip("/")
        r = http_get(root + "/api/tags", timeout=3)
        r.raise_for_status()
        installed = [m.get("name") for m in r.json().get("models", [])]
        loaded = None
        try:
            ps = http_get(root + "/api/ps", timeout=3)
            ps.raise_for_status()
            loaded = [m.get("name") for m in ps.json().get("models", [])]
        except Exception:  # noqa: BLE001 - /api/ps unavailable: unknown, not "nothing loaded"
            loaded = None
        out = {"ok": True, "runtime_running": True, "models": len(installed), "installed": installed,
               "loaded_models": loaded, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if model:
            out["model_installed"] = model in installed
            out["model_loaded"] = None if loaded is None else model in loaded
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "runtime_running": False, "error": type(exc).__name__,
               "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    if use_cache:
        _PROBE_CACHE[cache_key] = (time.monotonic(), dict(out))
    return out


def probe_cloud(adapter: Any) -> dict:
    """`adapter.list_models()` (GET /models: lists, spends no tokens) -- only with ANAMNESIA_ALLOW_NETWORK_TEST=1."""
    if not _on(NETWORK_FLAG):
        return {"skipped": f"{NETWORK_FLAG}!=1"}
    t0 = time.perf_counter()
    try:
        n = len(adapter.list_models())
        return {"ok": True, "models": n, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        from app.adapters.models.errors import classify_exception
        return {"ok": False, "error": type(exc).__name__, "error_kind": classify_exception(exc)[0],
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}


def health_report(tracker: HealthTracker | None = None, breaker: Any = None) -> dict:
    """Read-only, serialisable: real-call stats per model + circuit-breaker state."""
    tr = tracker or get_tracker()
    if breaker is None:
        from app.routing.circuit_breaker import get_breaker
        breaker = get_breaker()
    return {"enabled": health_enabled(), "models": tr.all_stats(), "circuits": breaker.snapshot()}
