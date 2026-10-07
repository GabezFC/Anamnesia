"""Escalation (R3): pure choice of the next model after failed attempts. No execution here."""
from __future__ import annotations


def next_model(decision, failed_attempts: int) -> str | None:
    """Model to try after `failed_attempts` failures of the chain so far (1 = the initial model failed).

    Returns None when there is nothing left or max_escalations is reached.
    """
    if decision is None or decision.model_id is None:
        return None
    n = int(failed_attempts)
    if n < 1 or n > decision.max_escalations:
        return None
    chain = decision.fallback_chain
    return chain[n - 1] if n - 1 < len(chain) else None
