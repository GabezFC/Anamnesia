"""EXPERIMENTAL / NOT WIRED (no runtime consumer yet; only tests import it). ContextPlan (ANA-159): memory + workspace + per-role budget, decided BEFORE delegating to an agent.

Pure data + arithmetic -- no search is executed here and nothing is written. `plan_for_run` splits a total
context budget among the steps of an orchestrated run in proportion to what each role needs; the caller
passes `ContextPlan.for_role(role)` as `memory_search(budget=...)` for that step.

Role weights follow the role contracts in app/orchestration/roles.py: the orchestrator only plans (small),
the researcher reads memory the most, the implementer needs files more than memory, the reviewer a diff.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

MIN_BUDGET = 200       # same floor as the MCP/REST `budget` parameter
MAX_BUDGET = 100000
DEFAULT_TOTAL = 6000
ROLE_WEIGHTS = {"orchestrator": 1.0, "researcher": 3.0, "implementer": 2.0, "reviewer": 1.5}


@dataclass(frozen=True)
class ContextPlan:
    total_budget: int
    per_role: dict[str, int]
    project: str | None = None
    worktree: str | None = None
    scope: str | None = None
    notes: list[str] = field(default_factory=list)

    def for_role(self, role: str) -> int:
        """Budget for one role; an unknown role gets the smallest share (never more than the total)."""
        return self.per_role.get(role, min(self.per_role.values(), default=MIN_BUDGET))

    def to_dict(self) -> dict:
        return {"total_budget": self.total_budget, "per_role": dict(self.per_role), "project": self.project,
                "worktree": self.worktree, "scope": self.scope, "notes": list(self.notes)}


def plan_for_run(roles: list[str], total_budget: int | None = None, *, project: str | None = None,
                 worktree: str | None = None, scope: str | None = None) -> ContextPlan:
    """Split `total_budget` over the roles of a run. Shares are proportional to ROLE_WEIGHTS, floored at
    MIN_BUDGET, and their sum never exceeds the total (the largest share absorbs rounding)."""
    if not roles:
        raise ValueError("roles vazio")
    total = int(total_budget or int(os.environ.get("ANAMNESIA_RUN_CONTEXT_BUDGET", DEFAULT_TOTAL) or DEFAULT_TOTAL))
    total = max(MIN_BUDGET, min(total, MAX_BUDGET))
    notes: list[str] = []
    uniq = list(dict.fromkeys(roles))
    if MIN_BUDGET * len(uniq) > total:
        total = MIN_BUDGET * len(uniq)
        notes.append("total elevado ao mínimo (200 por papel)")
    wsum = sum(ROLE_WEIGHTS.get(r, 1.0) for r in uniq)
    shares = {r: max(MIN_BUDGET, int(total * ROLE_WEIGHTS.get(r, 1.0) / wsum)) for r in uniq}
    over = sum(shares.values()) - total
    if over > 0:  # floors pushed the sum above the total: take it from the largest share
        big = max(shares, key=shares.get)
        shares[big] = max(MIN_BUDGET, shares[big] - over)
    return ContextPlan(total, shares, project, worktree, scope, notes)
