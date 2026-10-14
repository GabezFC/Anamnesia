"""ANA-171 provider error taxonomy + ANA-168 global paid-call kill-switch.

`classify_exception` maps whatever a provider raised (httpx status/transport errors, anthropic SDK
exceptions, JSON/shape errors) to ONE of `ERROR_KINDS`, plus the HTTP status and a `Retry-After` in
seconds when the server sent one. Pure: no network, no secrets (only the exception *type*, the status
code and a few fixed keywords of the body are inspected; the body is never stored).

Kill-switch: `ANAMNESIA_PAID_CALLS=0|false|no|off` makes every non-local provider refuse to run
(`PaidCallsDisabled`). Unset or any other value = allowed (default behaviour unchanged).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

ERROR_KINDS = ("auth", "rate_limit", "timeout", "context_overflow", "model_not_found", "provider_down",
               "bad_output", "other")
LOCAL_PROVIDERS = frozenset({"ollama", "vllm"})
_OFF = {"0", "false", "no", "off"}
_CONTEXT_WORDS = ("context length", "context_length", "maximum context", "too many tokens", "context window",
                  "prompt is too long", "reduce the length", "token limit", "input is too long")


class PaidCallsDisabled(RuntimeError):
    """Raised instead of building/calling a non-local adapter while ANAMNESIA_PAID_CALLS is off."""


def paid_calls_enabled() -> bool:
    return os.environ.get("ANAMNESIA_PAID_CALLS", "").strip().lower() not in _OFF


def is_local_provider(provider: str | None) -> bool:
    return (provider or "").lower() in LOCAL_PROVIDERS


def ensure_paid_allowed(provider: str | None) -> None:
    if not is_local_provider(provider):
        from app.services.offline import ensure_online  # ANA-224: OFFLINE=1 blocks every hosted provider
        ensure_online(f"provider:{provider}")
    if not is_local_provider(provider) and not paid_calls_enabled():
        raise PaidCallsDisabled(f"ANAMNESIA_PAID_CALLS=0: chamada ao provedor '{provider}' bloqueada")


def kind_from_status(status: int | None, body: str = "") -> str:
    if status is None:
        return "other"
    low = (body or "").lower()
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status in (408, 504):
        return "timeout"
    if status == 404:
        return "model_not_found" if ("model" in low or not low) else "other"
    if status in (400, 413, 422):
        if any(w in low for w in _CONTEXT_WORDS) or status == 413:
            return "context_overflow"
        if "model" in low and ("not found" in low or "does not exist" in low or "unknown" in low
                               or "not a valid model" in low):      # OpenRouter: 400 "<id> is not a valid model ID" (Onda 4e, real)
            return "model_not_found"
        return "other"
    if status >= 500:
        return "provider_down"
    return "other"


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds or HTTP-date). None if absent/invalid; never negative."""
    if value is None:
        return None
    v = str(value).strip()
    if not v:
        return None
    try:
        secs = float(v)
        return max(0.0, secs) if secs == secs and secs != float("inf") else None
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(v)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())
    except (TypeError, ValueError):
        return None


def classify_exception(exc: BaseException) -> tuple[str, int | None, float | None]:
    """(kind, status_code, retry_after_seconds)."""
    mro = {c.__name__ for c in type(exc).__mro__}
    status = getattr(exc, "status_code", None)
    resp = getattr(exc, "response", None)
    headers = None
    body = ""
    if resp is not None:
        status = status if isinstance(status, int) else getattr(resp, "status_code", None)
        headers = getattr(resp, "headers", None)
        try:
            body = (getattr(resp, "text", "") or "")[:2000]
        except Exception:  # noqa: BLE001 - streaming/closed response
            body = ""
    if not body and isinstance(status, int):
        body = str(exc)[:500]
    retry = parse_retry_after(headers.get("retry-after") if headers is not None else None)
    if isinstance(status, int):
        return kind_from_status(status, body), status, retry
    if isinstance(exc, PaidCallsDisabled):
        return "other", None, None
    if "ConnectTimeout" in mro:        # could not even connect (Windows reports a closed port this way)
        return "provider_down", None, retry
    if mro & {"TimeoutException", "APITimeoutError", "TimeoutError"}:
        return "timeout", None, retry
    if mro & {"ConnectError", "NetworkError", "APIConnectionError", "ConnectionError", "RemoteProtocolError",
              "ConnectionRefusedError", "ProxyError"}:
        return "provider_down", None, retry
    if isinstance(exc, (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError)):
        return "bad_output", None, None
    return "other", None, retry
