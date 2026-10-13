"""ANA-165: pre-flight cost ceiling for `scripts/run_routing_benchmark.py --real`.

Everything here is offline and free: it ESTIMATES (N x models x average tokens x price) before a single paid
call, REFUSES when the spend cannot be bounded, and wraps the runner in a guard that adds up the REAL cost of
each call and aborts the run once it exceeds the ceiling. Local models cost 0 money (marginal API cost).
A paid model with an unknown price is never priced at 0: it makes the estimate a lower bound and, without a
ceiling (--max-usd), the run is refused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.benchmark import routing_bench as rb
from app.routing.registry import ModelEntry
from app.routing.tasks import Task
from app.services.token_estimate import estimate_tokens

REFUSE_EXIT_CODE = 2
ABORT_EXIT_CODE = 3


class BudgetExceeded(RuntimeError):
    """Raised BEFORE a call once the real spend already went over the ceiling."""


@dataclass
class Preflight:
    ok: bool
    reason: str
    max_usd: float | None
    estimate_usd: float | None            # sum of KNOWN prices only (lower bound when `complete` is False)
    complete: bool                         # every paid model that would be called has a known price
    unpriced_paid: list[str] = field(default_factory=list)
    per_model: list[dict] = field(default_factory=list)
    n_calls: int = 0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason, "max_usd": self.max_usd, "estimate_usd": self.estimate_usd,
                "estimate_origin": "estimated" if self.complete else "lower_bound", "complete": self.complete,
                "unpriced_paid": self.unpriced_paid, "per_model": self.per_model, "n_calls": self.n_calls}


def models_to_call(models: Sequence[ModelEntry], strategies: Sequence[str], default_id: str | None = None) -> list[ModelEntry]:
    """Models that the chosen strategies could call. DYNAMIC_ROUTER/ORACLE may reach any model -> all of them."""
    models = list(models)
    if not models:
        return []
    if rb.DYNAMIC_ROUTER in strategies or rb.ORACLE in strategies or any(s.startswith(rb.DYNAMIC_ROUTER) for s in strategies):
        return models
    chosen: dict[str, ModelEntry] = {}
    if rb.STATIC_CHEAP in strategies:
        m = rb.cheapest(models)
        chosen[m.id] = m
    if rb.STATIC_DEFAULT in strategies:
        m = rb.default_model(models, default_id)
        chosen[m.id] = m
    if rb.STATIC_STRONG in strategies:
        m = rb.strongest(models)
        chosen[m.id] = m
    return list(chosen.values())


def estimate_run(tasks: Sequence[Task], called: Sequence[ModelEntry], repeats: int = 1, max_tokens: int = 400,
                 prompt_fn: Any = None) -> dict:
    """Per-model estimate. Input tokens = mean estimate over the prompts; output tokens = max_tokens (upper
    bound: temperature 0 answers are usually shorter). Unknown price -> cost None (never 0)."""
    prompt_fn = prompt_fn or rb.build_prompt
    n = len(tasks) * max(1, int(repeats))
    avg_in = (sum(estimate_tokens(prompt_fn(t)) for t in tasks) / len(tasks)) if tasks else 0.0
    per_model = []
    for m in called:
        rates = m.cost_per_mtok()
        if rates is None and m.local:        # local model: no marginal API money
            cost, status = 0.0, "local_zero"
        elif rates is None:
            cost, status = None, "unavailable"
        else:
            cost = round(n * (avg_in * rates["input"] + max_tokens * rates["output"]) / 1e6, 8)
            status = "local_zero" if m.local else "priced"
        per_model.append({"id": m.id, "local": m.local, "calls": n, "avg_input_tokens": round(avg_in, 1),
                          "output_tokens_cap": max_tokens, "price_status": status, "cost_usd": cost})
    return {"n_calls": n * len(per_model), "avg_input_tokens": round(avg_in, 1), "per_model": per_model}


def preflight(tasks: Sequence[Task], models: Sequence[ModelEntry], strategies: Sequence[str], *,
              repeats: int = 1, max_usd: float | None = None, default_id: str | None = None,
              max_tokens: int = 400, prompt_fn: Any = None) -> Preflight:
    called = models_to_call(models, strategies, default_id)
    est = estimate_run(tasks, called, repeats, max_tokens, prompt_fn)
    unpriced = [p["id"] for p in est["per_model"] if p["price_status"] == "unavailable" and not p["local"]]
    known = [p["cost_usd"] for p in est["per_model"] if p["cost_usd"] is not None]
    total = round(sum(known), 8) if known else (0.0 if not unpriced else None)
    base: dict[str, Any] = dict(max_usd=max_usd, estimate_usd=total, complete=not unpriced, unpriced_paid=unpriced,
                per_model=est["per_model"], n_calls=est["n_calls"])
    if max_usd is not None and max_usd < 0:
        return Preflight(False, "--max-usd must be >= 0", **base)
    if unpriced and max_usd is None:
        return Preflight(False, f"paid model(s) with UNKNOWN price {unpriced} and no ceiling: the spend cannot be "
                                f"bounded. Pass --max-usd or remove them from the registry/usable set.", **base)
    if max_usd is not None and total is not None and total > max_usd:
        return Preflight(False, f"estimate US$ {total:.6f}{'+' if unpriced else ''} > ceiling US$ {max_usd:.6f}", **base)
    why = "ok"
    if unpriced:
        why = (f"ok with caveat: {unpriced} have unknown prices; the estimate is a LOWER BOUND and the guard "
               f"cannot count their real cost (calls are tallied as unpriced)")
    return Preflight(True, why, **base)


class BudgetedRunner:
    """Wraps a ModelRunner. Adds up the REAL cost of every call; once the spend exceeds `max_usd` the NEXT call
    raises BudgetExceeded before touching the provider (so the call that crossed the line is kept, never lost).
    Calls priced None (unknown price / tokens) are counted in `unpriced_calls`, never as 0."""

    def __init__(self, inner: Any, max_usd: float | None):
        self._inner = inner
        self.max_usd = max_usd
        self.spent = 0.0
        self.calls = 0
        self.unpriced_calls = 0
        self.exceeded = False

    def __getattr__(self, name: str) -> Any:        # prompt_for / cache_params / simulated / context_fn ...
        return getattr(self._inner, name)

    def __call__(self, task: Task, entry: ModelEntry):
        if self.exceeded:
            raise BudgetExceeded(f"spent US$ {self.spent:.6f} > ceiling US$ {self.max_usd:.6f}; run aborted")
        out = self._inner(task, entry)
        self.calls += 1
        cost, _origin = rb.call_cost(entry, out)
        if cost is None and entry.local:
            cost = 0.0
        if cost is None:
            self.unpriced_calls += 1
        else:
            self.spent += cost
        if self.max_usd is not None and self.spent > self.max_usd:
            self.exceeded = True
        return out

    def report(self, estimate_usd: float | None, complete: bool = True) -> dict:
        ratio = None if not estimate_usd else round(self.spent / estimate_usd, 4)
        return {"spent_usd": round(self.spent, 8), "spent_origin": "measured" if self.unpriced_calls == 0 else "lower_bound",
                "estimate_usd": estimate_usd, "estimate_complete": complete, "ratio_real_over_estimate": ratio,
                "calls": self.calls, "unpriced_calls": self.unpriced_calls, "aborted": self.exceeded,
                "max_usd": self.max_usd}
