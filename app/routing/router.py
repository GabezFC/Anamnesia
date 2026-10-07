"""Deterministic model router (R3). Pure function: zero model calls, zero network, zero I/O.

Same input (query, context_tokens, task_kind, risk, registry file, policy) -> same decision.
Routing misses never raise: they return a RoutingDecision with model_id None and a reason code.
Nothing here is measured yet; see docs/MODEL_ROUTER.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.routing.policy import RISK_LEVELS, RoutingPolicy
from app.services.query_fp import _is_rare, classify, fold, tokens

_WORD = re.compile(r"\w+", re.UNICODE)
_CAMEL = re.compile(r"\b[a-z]+[A-Z]\w*|\b[A-Z][a-z]+[A-Z]\w*")
_PATH = re.compile(r"[\w.-]+[/\\][\w./\\-]+")
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-zA-Z]{2,}")


@dataclass
class RoutingDecision:
    model_id: str | None
    tier: int | None
    effort: str | None
    verify: str
    difficulty: float
    reason_codes: list = field(default_factory=list)
    registry_version: str = ""
    policy_version: str = ""
    fallback_chain: list = field(default_factory=list)      # model ids, increasing tier
    expected_cost_status: str = "unavailable"               # verified | local_zero | unavailable
    router_tokens: int = 0
    max_escalations: int = 0
    features: dict = field(default_factory=dict)            # audit: each feature value 0..1


def _sat(value: float, saturation: float) -> float:
    return 0.0 if saturation <= 0 else min(1.0, max(0.0, value / saturation))


def _hits(folded_padded: str, cues) -> int:
    n = 0
    for c in cues:
        fc = fold(c)
        if fc and fc in folded_padded:
            n += 1
    return n


def difficulty_features(query: str, context_tokens: int, policy: RoutingPolicy) -> dict:
    """Cheap features, each in [0, 1]. Reuses query_fp.classify() and its identifier heuristic."""
    q = query or ""
    folded = f" {fold(q)} "
    n_words = len(_WORD.findall(q))
    profile = classify(q)
    ids = {t for t in tokens(q) if _is_rare(t)}
    ids |= {m.lower() for m in _CAMEL.findall(q)}
    ids |= {m.lower() for m in _PATH.findall(q)}
    ids |= {m.lower() for m in _PROPER.findall(q)}
    multi = _hits(folded, policy.multi_hop_cues) + (1 if profile.multi_hop_hint else 0)
    return {
        "length": _sat(n_words, policy.length_saturation_tokens),
        "entities": _sat(len(ids), policy.entities_saturation),
        "multi_hop": _sat(multi, policy.multi_hop_saturation),
        "context": _sat(max(0, context_tokens or 0), policy.context_reference_tokens),
        "code": _sat(_hits(folded, policy.code_cues), policy.code_saturation),
        "reasoning": _sat(_hits(folded, policy.reasoning_cues), policy.reasoning_saturation),
        "classifier": float(policy.classifier_scores.get(profile.complexity, 0.5)),
    }


def difficulty_score(features: dict, policy: RoutingPolicy) -> float:
    total = sum(policy.weights.get(k, 0.0) for k in features)
    if total <= 0:
        return 0.0
    s = sum(policy.weights.get(k, 0.0) * v for k, v in features.items()) / total
    return round(min(1.0, max(0.0, s)), 6)


def _level(value: float, cutoffs) -> int:
    return sum(1 for c in cutoffs if value >= c)


def route(query, context_tokens, task_kind, risk, registry, policy, available_providers=None) -> RoutingDecision:
    reg_v = registry.version_hash() if registry is not None else ""
    pol_v = policy.version_hash()
    reasons: list[str] = []
    ctx = max(0, int(context_tokens or 0))

    def miss(code: str, diff: float = 0.0, feats=None, verify="NONE") -> RoutingDecision:
        return RoutingDecision(None, None, None, verify, diff, reasons + [code], reg_v, pol_v,
                               [], "unavailable", 0, policy.max_escalations, feats or {})

    if not policy.enabled:
        return miss("routing_disabled")

    feats = difficulty_features(query, ctx, policy)
    diff = difficulty_score(feats, policy)

    if risk not in RISK_LEVELS:
        reasons.append("unknown_risk_defaulted")
        risk = policy.default_risk
    reasons.append(f"risk_{risk}")
    verify = policy.verify_by_risk.get(risk, "LIGHT")

    caps = policy.task_capabilities.get(task_kind)
    if caps is None:
        reasons.append("unknown_task_kind")
        caps = []
    caps = list(caps)

    models = [] if registry is None else registry.eligible(
        capabilities=caps, available_providers=available_providers)
    if not models:
        return miss("no_eligible_model", diff, feats, verify)

    tiers = sorted({m.tier for m in models})
    if policy.always_top_tier:
        target_tier = tiers[-1]
        reasons.append("policy_always_top_tier")
    else:
        n_levels = len(policy.tier_cutoffs) + 1
        level = _level(diff, policy.tier_cutoffs)
        level = min(n_levels - 1, level + policy.risk_level_bump.get(risk, 0))
        level = max(level, min(policy.floor_level, n_levels - 1))
        idx = round(level * (len(tiers) - 1) / (n_levels - 1)) if n_levels > 1 else 0
        target_tier = tiers[idx]
        reasons.append(f"difficulty_level_{level}")

    at_target = [m for m in models if m.tier >= target_tier]
    fitting = [m for m in at_target if ctx == 0 or (m.context_window is not None and m.context_window >= ctx)]
    if not fitting:
        return _ctx_miss(reasons, diff, feats, verify, reg_v, pol_v, policy)
    chosen = fitting[0]
    if chosen is not at_target[0]:
        reasons.append("context_window_escalation")   # cheaper candidates did not fit the context

    # fallback: cheapest eligible model of each higher tier that also fits the context
    chain: list[str] = []
    seen = {chosen.tier}
    for m in fitting:
        if m.tier > chosen.tier and m.tier not in seen and len(chain) < policy.max_escalations:
            chain.append(m.id)
            seen.add(m.tier)

    effort = None
    if chosen.effort_supported:
        effort = policy.effort_levels[_level(diff, policy.effort_cutoffs)]
    else:
        reasons.append("effort_not_supported")

    # status comes from the registry; never a money estimate here
    return RoutingDecision(chosen.id, chosen.tier, effort, verify, diff, reasons, reg_v, pol_v,
                           chain, registry.price_status(chosen.id), 0, policy.max_escalations, feats)


def _ctx_miss(reasons, diff, feats, verify, reg_v, pol_v, policy) -> RoutingDecision:
    return RoutingDecision(None, None, None, verify, diff,
                           reasons + ["no_eligible_model", "context_window_unfit"], reg_v, pol_v,
                           [], "unavailable", 0, policy.max_escalations, feats)
