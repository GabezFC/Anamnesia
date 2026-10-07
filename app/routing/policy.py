"""Routing policy (R2): every tunable number of the router lives HERE, none in the logic.

All weights/thresholds are INITIAL GUESSES. Nothing has been measured; the benchmark (R6) is what
may tune them. Routing is DISABLED by default (`enabled=False`) and not wired into memory_search.
Pure data + hashing: no model calls, no network, no I/O.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field

VERIFY_LEVELS = ("NONE", "LIGHT", "FULL")
RISK_LEVELS = ("low", "medium", "high")
PRESET_NAMES = ("economic", "balanced", "max")


def _default_weights() -> dict[str, float]:
    return {
        "length": 1.0,          # query length in tokens
        "entities": 1.0,        # distinct identifiers / proper names
        "multi_hop": 2.0,       # conjunction / comparison / sequencing cues
        "context": 1.0,         # context_tokens relative to a reference size
        "code": 1.0,            # code cues
        "reasoning": 1.5,       # reasoning cues
        "classifier": 1.0,      # query_fp.classify() class (reused heuristic)
    }


@dataclass
class RoutingPolicy:
    name: str = "default"
    enabled: bool = False                      # routing OFF unless explicitly turned on
    # ---- difficulty features
    weights: dict = field(default_factory=_default_weights)
    length_saturation_tokens: int = 40         # length feature reaches 1.0 here
    entities_saturation: int = 5
    multi_hop_saturation: int = 2              # cue hits that give feature 1.0
    code_saturation: int = 2
    reasoning_saturation: int = 2
    context_reference_tokens: int = 32000      # context feature reaches 1.0 here
    classifier_scores: dict = field(default_factory=lambda: {
        "SIMPLE": 0.0, "MEDIUM": 0.5, "COMPLEX": 1.0, "AMBIGUOUS": 0.5})
    # Cues are matched on accent-folded, lower-cased text (PT and EN).
    multi_hop_cues: tuple = (
        "e depois", "and then", "em seguida", "compare", "comparar", "comparacao",
        "comparison", "versus", " vs ", "diferenca entre", "difference between", "antes e depois",
        "before and after", "both", "ambos", "alem disso", "furthermore", "por outro lado",
        "on the other hand", "relacao entre", "relationship between", "impacto", "consequencia",
        "consequences", "e tambem", "as well as", "cada um", "each of",
    )
    code_cues: tuple = (
        "```", "def ", "class ", "function", "funcao", "traceback", "stacktrace", "exception",
        "bug", "refactor", "refatorar", "compile", "stack trace", ".py", ".ts", ".js", "sql",
        "regex", "implement", "implementar", "unit test", "teste unitario",
    )
    reasoning_cues: tuple = (
        "por que", "porque", "why", "prove", "provar", "deduza", "deduce", "infer", "analise",
        "analyze", "analyse", "trade-off", "tradeoff", "avalie", "evaluate", "justifique",
        "justify", "explique", "explain", "step by step", "passo a passo", "pros and cons",
        "prós e contras", "pros e contras",
    )
    # ---- difficulty -> minimum tier. `tier_cutoffs` split [0,1] into len+1 levels; levels are
    # mapped onto the tiers PRESENT in the registry (no fixed tier count).
    tier_cutoffs: tuple = (0.25, 0.5, 0.75)
    floor_level: int = 0                       # lowest level ever used
    always_top_tier: bool = False              # 'max': always the highest tier available
    # ---- risk
    default_risk: str = "medium"
    risk_level_bump: dict = field(default_factory=lambda: {"low": 0, "medium": 0, "high": 1})
    verify_by_risk: dict = field(default_factory=lambda: {
        "low": "NONE", "medium": "LIGHT", "high": "FULL"})
    # ---- effort (only used when the chosen model has effort_supported)
    effort_cutoffs: tuple = (0.34, 0.67)
    effort_levels: tuple = ("low", "medium", "high")
    # ---- escalation
    max_escalations: int = 2
    # ---- task kind -> required registry capabilities
    task_capabilities: dict = field(default_factory=lambda: {
        "code": ["code"], "reasoning": ["reasoning"], "bulk": ["cheap_bulk"],
        "vision": ["vision"], "tools": ["tools"], "memory": [], "general": [],
    })

    def __post_init__(self):
        if self.default_risk not in RISK_LEVELS:
            raise ValueError(f"default_risk must be one of {RISK_LEVELS}")
        for r, v in self.verify_by_risk.items():
            if r not in RISK_LEVELS or v not in VERIFY_LEVELS:
                raise ValueError(f"invalid verify_by_risk entry {r!r}: {v!r}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be >= 0")
        if list(self.tier_cutoffs) != sorted(self.tier_cutoffs):
            raise ValueError("tier_cutoffs must be ascending")
        if len(self.effort_levels) != len(self.effort_cutoffs) + 1:
            raise ValueError("effort_levels must have len(effort_cutoffs)+1 entries")
        if self.max_escalations < 0:
            raise ValueError("max_escalations must be >= 0")

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def version_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, default=list)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def with_enabled(self, enabled: bool = True) -> "RoutingPolicy":
        return dataclasses.replace(self, enabled=enabled)


def preset(name: str, enabled: bool = False) -> RoutingPolicy:
    """Named presets matching the Config-tab ones (Econômico / Equilibrado / Máximo)."""
    if name == "economic":
        p = RoutingPolicy(
            name="economic", tier_cutoffs=(0.4, 0.7, 0.9), floor_level=0, max_escalations=2,
            risk_level_bump={"low": 0, "medium": 0, "high": 0},
            verify_by_risk={"low": "LIGHT", "medium": "LIGHT", "high": "LIGHT"})
    elif name == "balanced":
        p = RoutingPolicy(
            name="balanced", tier_cutoffs=(0.25, 0.5, 0.75), floor_level=1, max_escalations=2,
            verify_by_risk={"low": "LIGHT", "medium": "LIGHT", "high": "FULL"})
    elif name == "max":
        p = RoutingPolicy(
            name="max", always_top_tier=True, floor_level=0, max_escalations=0,
            verify_by_risk={"low": "FULL", "medium": "FULL", "high": "FULL"})
    else:
        raise ValueError(f"unknown preset {name!r}; expected one of {PRESET_NAMES}")
    return p.with_enabled(enabled)
