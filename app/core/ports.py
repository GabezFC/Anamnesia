"""Ports (Protocols) shared across layers so low layers need not import high ones.

ANA-132: `Retriever` / `Judge` -- a pipeline is a composition of retrievers + (optional) judge.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Retriever(Protocol):
    """Candidate source, decoupled from the gateway (ANA-132)."""

    def search(self, query: str, scope: Any, k: int) -> list[Any]:
        """Return up to `k` `Candidate`s for `query` restricted to `scope` (None/global = all)."""
        ...


@runtime_checkable
class Judge(Protocol):
    """Optional stage after retrieval; same contract as `JEVService.evaluate`."""

    def evaluate(self, query: str, candidates: list[Any]) -> tuple[list[Any], dict[str, Any]]:
        ...
