"""ANA-177: fallback policy BY CAUSE + the guarded call used by the answer loop.

`decide()` is a pure table kind -> Action (from `app.adapters.models.errors.ERROR_KINDS`):

  rate_limit        retry with backoff+jitter honouring Retry-After, then SWITCH_PROVIDER (same tier)
  timeout           retry once, then SWITCH_PROVIDER
  provider_down     retry once, then SWITCH_PROVIDER
  auth              SKIP_PROVIDER   (never escalate the tier: a bigger model on the same bad key fails too)
  model_not_found   SKIP_PROVIDER
  context_overflow  ESCALATE_LARGER_WINDOW if a larger window is known, else ABORT
  bad_output        ESCALATE_TIER
  other             ESCALATE_TIER   (the legacy behaviour)

Flags (all default OFF; with none set `guarded_generate` is a straight call and the answer loop is the legacy one):
  ANAMNESIA_RETRY=1              retry/backoff (app/routing/retry.py)
  ANAMNESIA_CIRCUIT_BREAKER=1    skip open circuits, feed the breaker (app/routing/circuit_breaker.py)
  ANAMNESIA_FALLBACK_BY_CAUSE=1  choose the next model by `decide()` instead of "next tier in the chain"
  ANAMNESIA_HEALTH=1             record real-call outcomes for health (app/routing/health.py)
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.routing import circuit_breaker as cb
from app.routing import health as hl
from app.routing import retry as rt
from app.routing.escalation import next_model

FALLBACK_FLAG = "ANAMNESIA_FALLBACK_BY_CAUSE"

RETRY, SWITCH_PROVIDER, SKIP_PROVIDER = "retry", "switch_provider", "skip_provider"
ESCALATE_TIER, ESCALATE_LARGER_WINDOW, ABORT = "escalate_tier", "escalate_larger_window", "abort"

# Hooks looked up at call time so tests inject fake time (no real sleeping).
SLEEP: Callable[[float], None] = time.sleep
CLOCK: Callable[[], float] = time.monotonic


def fallback_by_cause_enabled() -> bool:
    return os.environ.get(FALLBACK_FLAG, "").strip().lower() in ("1", "true", "yes", "on")


def any_enabled() -> bool:
    return rt.retry_enabled() or cb.breaker_enabled() or fallback_by_cause_enabled() or hl.health_enabled()


@dataclass(frozen=True)
class Action:
    name: str
    delay_s: float = 0.0
    reason: str = ""


def decide(kind: str | None, attempt: int = 0, retry_after: float | None = None, *, max_retries: int = 1,
           has_larger_window: bool = False, policy: rt.RetryPolicy | None = None) -> Action:
    """Pure. `attempt` = retries already made on this model; `max_retries` = how many this cause may get."""
    if kind == "rate_limit":
        if attempt < max_retries:
            return Action(RETRY, rt.backoff_delay(attempt, policy or rt.RetryPolicy(), retry_after=retry_after),
                          "rate_limit: backoff/Retry-After")
        return Action(SWITCH_PROVIDER, 0.0, "rate_limit: retries exhausted -> other provider, same tier")
    if kind in ("timeout", "provider_down"):
        if attempt < min(1, max_retries):
            return Action(RETRY, rt.backoff_delay(attempt, policy or rt.RetryPolicy(), retry_after=retry_after),
                          f"{kind}: retry once")
        return Action(SWITCH_PROVIDER, 0.0, f"{kind}: -> other provider, same tier")
    if kind in ("auth", "model_not_found"):
        return Action(SKIP_PROVIDER, 0.0, f"{kind}: skip provider, do not escalate tier")
    if kind == "context_overflow":
        return (Action(ESCALATE_LARGER_WINDOW, 0.0, "context_overflow: larger window") if has_larger_window
                else Action(ABORT, 0.0, "context_overflow: no larger window known"))
    return Action(ESCALATE_TIER, 0.0, f"{kind or 'other'}: next tier")


# ------------------------------------------------------------------ guarded call
def guarded_generate(entry, make_adapter_fn: Callable, avail: dict | None, prompt: str, info: dict, **gen_kw):
    """Adapter call used by the answer loop. No flag -> exactly `make_adapter_fn(entry, avail).generate(...)`
    (exceptions propagate unchanged). With flags: breaker gate -> retry/backoff -> breaker/health feedback.
    `info` is filled: retries, waited_s, circuit_open, retry_log. Returns a result or raises (legacy contract)."""
    if not any_enabled():
        return make_adapter_fn(entry, avail).generate(prompt, **gen_kw)
    key = cb.key_for(getattr(entry, "provider", None), getattr(entry, "model", None))
    use_cb = cb.breaker_enabled()
    breaker = cb.get_breaker() if use_cb else None
    if breaker is not None and not breaker.allow(key):
        info["circuit_open"] = True
        from app.adapters.models.providers import GenerationResult
        return GenerationResult(None, None, None, 0.0, getattr(entry, "provider", "?"), getattr(entry, "model", "?"),
                                f"circuit_open: {key}", error_kind="provider_down")
    pol = rt.RetryPolicy.from_env() if rt.retry_enabled() else rt.RetryPolicy(max_retries=0)
    t0 = time.perf_counter()
    out = rt.call_with_retry(lambda: make_adapter_fn(entry, avail).generate(prompt, **gen_kw), pol,
                             sleep=lambda s: SLEEP(s), clock=lambda: CLOCK())
    kind, _status, _ra = rt.outcome_kind(out.result, out.exc)
    info.update(retries=out.retries, waited_s=round(out.waited_s, 3), retry_log=out.log, gave_up=out.gave_up)
    if breaker is not None:
        breaker.record_success(key) if kind is None else breaker.record_failure(key, kind)
    if hl.health_enabled():
        hl.get_tracker().record(key, kind is None, round((time.perf_counter() - t0) * 1000, 1), kind)
    if out.exc is not None:
        raise out.exc
    return out.result


# ------------------------------------------------------------------ next-model choice
def _window(entry) -> int | None:
    return getattr(entry, "context_window", None)


def choose_next(decision, reg, current, kind: str, action: Action, tried: set, failed: int,
                banned_providers: set) -> str | None:
    """Next model id for a failed attempt, by cause. Respects `decision.max_escalations` as total cap,
    never repeats a model, never returns a model of a banned provider or with an open circuit."""
    if failed < 1 or failed > decision.max_escalations or action.name == ABORT:
        return None
    use_cb = cb.breaker_enabled()
    chain = [m for m in decision.fallback_chain if m not in tried]

    def ok(entry) -> bool:
        if entry.id in tried or entry.provider in banned_providers:
            return False
        return not (use_cb and cb.get_breaker().state(cb.key_for(entry.provider, entry.model)) == cb.OPEN)

    def entries(ids):
        out = []
        for i in ids:
            try:
                e = reg.get(i)
            except KeyError:
                continue
            if ok(e):
                out.append(e)
        return out

    if action.name in (SWITCH_PROVIDER, SKIP_PROVIDER):
        same_tier = [e for e in reg.models if e.tier == current.tier and e.provider != current.provider and ok(e)]
        if same_tier:
            return same_tier[0].id
        up = [e for e in entries(chain) if e.provider != current.provider]
        return up[0].id if up else None
    if action.name == ESCALATE_LARGER_WINDOW:
        cw = _window(current) or 0
        big = [e for e in entries(chain) if _window(e) and _window(e) > cw]
        return big[0].id if big else None
    cand = entries(chain)                       # ESCALATE_TIER
    return cand[0].id if cand else None


def has_larger_window(decision, reg, current, tried: set) -> bool:
    cw = _window(current) or 0
    for i in decision.fallback_chain:
        try:
            e = reg.get(i)
        except KeyError:
            continue
        if i not in tried and _window(e) and _window(e) > cw:
            return True
    return False


def next_after_failure(decision, reg, entry, attempts: list, info: dict, failed: int) -> str | None:
    """Next model id after the last attempt in `attempts` failed. Flag off, or the failure has no error kind
    (e.g. grounding_failed) -> the legacy `next_model(decision, failed)`. Otherwise by cause (`decide`); the
    chosen action is recorded on the attempt as `fallback_action` / `fallback_reason`."""
    att = attempts[-1]
    kind = att.get("error_kind")
    if not fallback_by_cause_enabled() or not kind:
        return next_model(decision, failed)
    tried = {a["model_id"] for a in attempts}
    banned = set()
    for a in attempts:
        if a.get("error_kind") in ("auth", "model_not_found"):
            try:
                banned.add(reg.get(a["model_id"]).provider)
            except KeyError:
                pass
    pol = rt.RetryPolicy.from_env() if rt.retry_enabled() else rt.RetryPolicy(max_retries=0)
    done = pol.max_retries if info.get("circuit_open") else int(info.get("retries") or 0)
    # retries already happened inside guarded_generate: here only the post-retry action matters
    action = decide(kind, max(done, pol.max_retries), att.get("retry_after"), max_retries=pol.max_retries,
                    has_larger_window=has_larger_window(decision, reg, entry, tried), policy=pol)
    att["fallback_action"], att["fallback_reason"] = action.name, action.reason
    return choose_next(decision, reg, entry, kind, action, tried, failed, banned)


__all__ = ["Action", "decide", "guarded_generate", "choose_next", "has_larger_window", "next_after_failure", "next_model",
           "fallback_by_cause_enabled", "any_enabled"]
