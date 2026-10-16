"""Escalation (R3): pure choice of the next model after failed attempts. No execution here."""
from __future__ import annotations


def next_model(decision, failed_attempts: int, allowed=None) -> str | None:
    """Model to try after `failed_attempts` failures of the chain so far (1 = the initial model failed).

    Returns None when there is nothing left or max_escalations is reached.
    ANAM-033 / AUD-099: the chain is filtered at escalation time by `allowed` (iterable of model ids) and by
    `decision.allowed_models` (set by the router for private data). A private decision with no permitted
    model yields None -- never an unfiltered chain entry.
    """
    if decision is None or decision.model_id is None:
        return None
    n = int(failed_attempts)
    if n < 1 or n > decision.max_escalations:
        return None
    chain = list(decision.fallback_chain)
    for restriction in (getattr(decision, "allowed_models", None), allowed):
        if restriction is not None:
            ok = set(restriction)
            chain = [m for m in chain if m in ok]
    return chain[n - 1] if n - 1 < len(chain) else None
