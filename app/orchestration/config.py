"""Orchestration config loader (config/orchestration.yaml) with validation.

Model classes (strong|medium|cheap) are mapped onto the registry tiers BY RANK, never by model id.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.routing.policy import PRESET_NAMES
from app.routing.registry import RegistryError, _parse_yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "orchestration.yaml"
ROLES = ("orchestrator", "researcher", "implementer", "reviewer")


class OrchestrationConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ClassRange:
    name: str
    rank_min: float
    rank_max: float


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    routing_preset: str
    roles: dict  # role -> class name


@dataclass(frozen=True)
class Limits:
    max_parallel_subagents: int = 3
    budget_usd: float | None = None
    escalate_on_failures: int = 2
    max_escalations_per_step: int = 1
    step_timeout_s: float = 600.0
    poll_interval_s: float = 0.5


@dataclass(frozen=True)
class OrchestrationConfig:
    class_order: tuple
    classes: dict
    presets: dict
    limits: Limits = field(default_factory=Limits)

    def preset(self, name: str) -> Preset:
        try:
            return self.presets[name]
        except KeyError:
            raise OrchestrationConfigError(
                f"unknown preset {name!r}; expected one of {sorted(self.presets)}") from None

    def class_tiers(self, registry_tiers) -> dict:
        return class_tiers(registry_tiers, self)

    def classes_from(self, cls: str) -> list:
        """`cls` and every class above it, low -> high."""
        i = self.class_order.index(cls)
        return list(self.class_order[i:])


def class_tiers(registry_tiers, cfg: OrchestrationConfig) -> dict:
    """{class: [registry tiers]} by rank position. Works for any number of tiers (>=1).

    One tier: every class maps onto it. Classes without a tier in range map to [] (the caller falls to the
    class above, see `OrchestrationConfig.classes_from`).
    """
    tiers = sorted(set(registry_tiers))
    n = len(tiers)
    out = {c: [] for c in cfg.class_order}
    if n == 0:
        return out
    if n == 1:
        return {c: [tiers[0]] for c in cfg.class_order}
    for i, t in enumerate(tiers):
        pos = i / (n - 1)
        for c in cfg.class_order:
            r = cfg.classes[c]
            if r.rank_min <= pos <= r.rank_max:
                out[c].append(t)
                break
    return out


def _num(v, where, lo=None, hi=None, allow_none=False):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise OrchestrationConfigError(f"{where}: must be a number, got {v!r}")
    if lo is not None and v < lo:
        raise OrchestrationConfigError(f"{where}: must be >= {lo}, got {v}")
    if hi is not None and v > hi:
        raise OrchestrationConfigError(f"{where}: must be <= {hi}, got {v}")
    return v


def parse_config(doc) -> OrchestrationConfig:
    if not isinstance(doc, dict):
        raise OrchestrationConfigError("config must be a mapping")
    order = doc.get("class_order")
    if not isinstance(order, list) or not order or not all(isinstance(c, str) for c in order) \
            or len(set(order)) != len(order):
        raise OrchestrationConfigError("class_order must be a non-empty list of unique class names")
    raw_classes = doc.get("classes")
    if not isinstance(raw_classes, dict) or set(raw_classes) != set(order):
        raise OrchestrationConfigError("classes must define exactly the names in class_order")
    classes = {}
    for name in order:
        c = raw_classes[name]
        if not isinstance(c, dict):
            raise OrchestrationConfigError(f"classes.{name}: must be a mapping")
        lo = _num(c.get("rank_min"), f"classes.{name}.rank_min", 0, 1)
        hi = _num(c.get("rank_max"), f"classes.{name}.rank_max", 0, 1)
        if lo > hi:
            raise OrchestrationConfigError(f"classes.{name}: rank_min > rank_max")
        classes[name] = ClassRange(name, float(lo), float(hi))
    prev_hi = -1.0
    for name in order:
        if classes[name].rank_min <= prev_hi:
            raise OrchestrationConfigError(f"classes.{name}: range overlaps the previous class")
        prev_hi = classes[name].rank_max
    raw_presets = doc.get("presets")
    if not isinstance(raw_presets, dict) or not raw_presets:
        raise OrchestrationConfigError("presets must be a non-empty mapping")
    presets = {}
    for name, p in raw_presets.items():
        if not isinstance(p, dict):
            raise OrchestrationConfigError(f"presets.{name}: must be a mapping")
        rp = p.get("routing_preset", name)
        if rp not in PRESET_NAMES:
            raise OrchestrationConfigError(f"presets.{name}.routing_preset: {rp!r} not in {PRESET_NAMES}")
        roles = p.get("roles")
        if not isinstance(roles, dict) or set(roles) != set(ROLES):
            raise OrchestrationConfigError(f"presets.{name}.roles must define exactly {list(ROLES)}")
        for r, c in roles.items():
            if c not in classes:
                raise OrchestrationConfigError(f"presets.{name}.roles.{r}: unknown class {c!r}")
        presets[name] = Preset(name, str(p.get("label") or name), rp, dict(roles))
    lim = doc.get("limits") or {}
    if not isinstance(lim, dict):
        raise OrchestrationConfigError("limits must be a mapping")
    d = Limits()
    limits = Limits(
        max_parallel_subagents=int(_num(lim.get("max_parallel_subagents", d.max_parallel_subagents),
                                        "limits.max_parallel_subagents", 1)),
        budget_usd=_num(lim.get("budget_usd"), "limits.budget_usd", 0, allow_none=True),
        escalate_on_failures=int(_num(lim.get("escalate_on_failures", d.escalate_on_failures),
                                      "limits.escalate_on_failures", 1)),
        max_escalations_per_step=int(_num(lim.get("max_escalations_per_step", d.max_escalations_per_step),
                                          "limits.max_escalations_per_step", 0)),
        step_timeout_s=float(_num(lim.get("step_timeout_s", d.step_timeout_s), "limits.step_timeout_s", 0.001)),
        poll_interval_s=float(_num(lim.get("poll_interval_s", d.poll_interval_s), "limits.poll_interval_s", 0.0)),
    )
    return OrchestrationConfig(tuple(order), classes, presets, limits)


def load_config(path=None) -> OrchestrationConfig:
    p = Path(path) if path else DEFAULT_PATH
    try:
        text = p.read_bytes().decode("utf-8")
    except OSError as e:
        raise OrchestrationConfigError(f"cannot read {p}: {e}") from e
    try:
        doc = _parse_yaml(text)
    except RegistryError as e:
        raise OrchestrationConfigError(str(e)) from e
    return parse_config(doc)
