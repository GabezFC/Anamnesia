"""ANA-186: shadow routing. Computes what an ALTERNATIVE policy would have chosen, WITHOUT executing it.

* Off unless ANAMNESIA_ROUTING_SHADOW=1. Off => `shadow_decision` is never computed and nothing changes.
* Zero model calls, zero network, no availability probe: only `route()` (pure) over the static registry.
* The result is recorded in the run's metrics_json under `shadow_decision`, stamped with the hashes of the
  reference and alternative policies and of the registry, so any divergence can be replayed later.
* The alternative never reaches the user: `executed` is always False.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Iterable

from app.routing.policy import PRESET_NAMES, RoutingPolicy, preset
from app.routing.router import route

ENV_FLAG = "ANAMNESIA_ROUTING_SHADOW"
ENV_PRESET = "ANAMNESIA_ROUTING_SHADOW_PRESET"     # alternative preset name; default: see alt_preset_name()
REFERENCE_FALLBACK = "balanced"                    # reference when the active policy is disabled (default)

_local = threading.local()


def shadow_enabled() -> bool:
    return os.getenv(ENV_FLAG, "").strip() == "1"


def alt_preset_name(reference_name: str) -> str:
    want = os.getenv(ENV_PRESET, "").strip()
    if want in PRESET_NAMES and want != reference_name:
        return want
    return "economic" if reference_name != "economic" else "balanced"


def _decision_view(d) -> dict:
    return {"model_id": d.model_id, "tier": d.tier, "effort": d.effort, "difficulty": d.difficulty,
            "verify": d.verify, "reason_codes": list(d.reason_codes)}


def compute_shadow(query: str, context_tokens: int, task_kind: str, risk: str, registry,
                   active_policy: RoutingPolicy, alt_policy: RoutingPolicy | None = None) -> dict:
    """Pure. `reference` = the active policy (or `balanced` if routing is off); `alternative` = another preset.
    Both are evaluated with routing enabled in memory only; nothing is executed."""
    t0 = time.perf_counter()
    ref = active_policy if active_policy.enabled else preset(REFERENCE_FALLBACK, enabled=True)
    alt = (alt_policy or preset(alt_preset_name(ref.name), enabled=True)).with_enabled(True)
    d_ref = route(query, context_tokens, task_kind, risk, registry, ref)
    d_alt = route(query, context_tokens, task_kind, risk, registry, alt)
    return {
        "executed": False, "model_calls": 0,
        "task_kind": task_kind, "risk": risk,
        "reference": {"policy": ref.name, "policy_hash": ref.version_hash(), "active": bool(active_policy.enabled),
                      **_decision_view(d_ref)},
        "alternative": {"policy": alt.name, "policy_hash": alt.version_hash(), **_decision_view(d_alt)},
        "registry_hash": d_ref.registry_version,
        "diverges": (d_ref.model_id, d_ref.tier) != (d_alt.model_id, d_alt.tier),
        "decision_ms": round((time.perf_counter() - t0) * 1000, 3),
    }


# -- hand-off between answer.plan_route (computes) and answer._persist (writes metrics_json) ------------
def stash(shadow: dict | None) -> None:
    _local.pending = shadow


def pop_pending() -> dict | None:
    s = getattr(_local, "pending", None)
    _local.pending = None
    return s


def maybe_shadow(query, context_tokens, task_kind, risk, registry, active_policy) -> None:
    """Called by plan_route. Never raises, never changes the real decision."""
    stash(None)
    if not shadow_enabled():
        return
    try:
        stash(compute_shadow(query, context_tokens, task_kind, risk, registry, active_policy))
    except Exception as exc:  # noqa: BLE001 — shadow must never break an answer
        stash({"executed": False, "model_calls": 0, "error": f"{type(exc).__name__}"})


# -- report -------------------------------------------------------------------------------------------
def divergence_report(records: Iterable[dict]) -> dict:
    """records: metrics dicts (with `shadow_decision`) or the shadow dicts themselves.
    Divergence rate overall and by risk / task_kind / reference->alternative tier move."""
    rows = []
    for r in records:
        s = r.get("shadow_decision", r) if isinstance(r, dict) else None
        if isinstance(s, dict) and "reference" in s and "alternative" in s:
            rows.append(s)
    n = len(rows)
    by: dict[str, dict[str, list[int]]] = {"risk": defaultdict(lambda: [0, 0]), "task_kind": defaultdict(lambda: [0, 0]),
                                           "tier_move": defaultdict(lambda: [0, 0])}
    moves = Counter()
    for s in rows:
        div = int(bool(s.get("diverges")))
        mv = f"t{s['reference'].get('tier')}->t{s['alternative'].get('tier')}"
        moves[mv] += 1
        for k, v in (("risk", s.get("risk")), ("task_kind", s.get("task_kind")), ("tier_move", mv)):
            by[k][str(v)][0] += 1
            by[k][str(v)][1] += div
    total_div = sum(int(bool(s.get("diverges"))) for s in rows)
    return {
        "n": n, "diverged": total_div, "divergence_rate": round(total_div / n, 4) if n else None,
        "model_calls": sum(int(s.get("model_calls", 0)) for s in rows),
        "policy_hashes": sorted({(s["reference"]["policy_hash"][:12], s["alternative"]["policy_hash"][:12]) for s in rows}),
        "by_category": {k: {c: {"n": v[0], "diverged": v[1], "rate": round(v[1] / v[0], 4)} for c, v in sorted(d.items())}
                        for k, d in by.items()},
        "tier_moves": dict(sorted(moves.items())),
    }
