"""ANA-178: bounded retry with exponential backoff, deterministic jitter and `Retry-After`.

Pure helpers + one driver (`call_with_retry`). Opt-in: `ANAMNESIA_RETRY=1` (default OFF; the answer
loop calls the adapter exactly once, as before). Only transient causes are retried:
`timeout`, `rate_limit` (429) and `provider_down` (5xx / connection errors). auth, model_not_found,
context_overflow, bad_output and other are NEVER retried (retrying cannot fix them).

Time is injectable (`sleep`, `clock`, `jitter_fn`) so tests never wait. A `Retry-After` from the
server wins over the computed backoff; if honouring it would exceed the per-request time ceiling
(`total_budget_s`) the retry is not attempted at all (we do not sleep half a budget and then fail).
Nothing here logs prompts, bodies or keys: the log holds only kind/status/delay numbers.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.adapters.models.errors import classify_exception

ENV_FLAG = "ANAMNESIA_RETRY"
RETRYABLE_KINDS = frozenset({"timeout", "rate_limit", "provider_down"})


def retry_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def _env_num(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 2            # extra attempts after the first (spec: 1-2)
    base_delay_s: float = 0.5
    factor: float = 2.0
    max_delay_s: float = 8.0        # cap of a *computed* backoff step
    jitter: float = 0.25            # +/- fraction of the step
    total_budget_s: float = 20.0    # ceiling for all waiting+calling of one request

    @classmethod
    def from_env(cls) -> "RetryPolicy":
        d = cls()
        return cls(max_retries=max(0, min(2, int(_env_num("ANAMNESIA_RETRY_MAX", d.max_retries)))),
                   base_delay_s=_env_num("ANAMNESIA_RETRY_BASE_S", d.base_delay_s),
                   total_budget_s=_env_num("ANAMNESIA_RETRY_BUDGET_S", d.total_budget_s))


def default_jitter(attempt: int, key: str = "") -> float:
    """Deterministic value in [0, 1) from (key, attempt): same inputs -> same delay, no RNG state."""
    h = hashlib.sha256(f"{key}:{attempt}".encode()).digest()
    return int.from_bytes(h[:4], "big") / 2 ** 32


def backoff_delay(attempt: int, policy: RetryPolicy, jitter_fn: Callable[[int], float] | None = None,
                  retry_after: float | None = None) -> float:
    """Delay before retry number `attempt` (0-based). Retry-After wins; otherwise
    min(max_delay, base*factor**attempt) * (1 +/- jitter)."""
    if retry_after is not None:
        return max(0.0, float(retry_after))
    step = min(policy.max_delay_s, policy.base_delay_s * policy.factor ** attempt)
    j = (jitter_fn or default_jitter)(attempt)
    return max(0.0, step * (1.0 + policy.jitter * (2.0 * j - 1.0)))


def outcome_kind(result: Any, exc: BaseException | None) -> tuple[str | None, int | None, float | None]:
    """(kind, status, retry_after) of one attempt; kind None = success."""
    if exc is not None:
        return classify_exception(exc)
    if result is not None and getattr(result, "error", None):
        return (getattr(result, "error_kind", None) or "other", getattr(result, "status_code", None),
                getattr(result, "retry_after", None))
    return None, None, None


@dataclass
class RetryOutcome:
    result: Any = None
    exc: BaseException | None = None
    retries: int = 0
    waited_s: float = 0.0
    gave_up: str | None = None      # None | "not_retryable" | "max_retries" | "time_budget"
    log: list = None                # [{"attempt","kind","status","delay_s"}]


def call_with_retry(fn: Callable[[], Any], policy: RetryPolicy | None = None, *,
                    sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic,
                    jitter_fn: Callable[[int], float] | None = None) -> RetryOutcome:
    """Run `fn()` (returns a GenerationResult-like or raises); retry transient failures.

    Returns the LAST attempt: `.result` (maybe carrying `.error`) or `.exc`. Never raises for provider errors.
    """
    pol = policy or RetryPolicy()
    t0 = clock()
    out = RetryOutcome(log=[])
    attempt = 0
    while True:
        res, exc = None, None
        try:
            res = fn()
        except Exception as e:  # noqa: BLE001
            exc = e
        out.result, out.exc = res, exc
        kind, status, retry_after = outcome_kind(res, exc)
        if kind is None:
            return out
        step = {"attempt": attempt, "kind": kind, "status": status, "delay_s": None}
        out.log.append(step)
        if kind not in RETRYABLE_KINDS:
            out.gave_up = "not_retryable"
            return out
        if attempt >= pol.max_retries:
            out.gave_up = "max_retries"
            return out
        delay = backoff_delay(attempt, pol, jitter_fn, retry_after)
        if (clock() - t0) + delay > pol.total_budget_s:
            out.gave_up = "time_budget"
            return out
        step["delay_s"] = round(delay, 3)
        sleep(delay)
        out.waited_s += delay
        out.retries += 1
        attempt += 1
