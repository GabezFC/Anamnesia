"""Agent catalog (config/agents.yaml): ONE entry per CLI agent, plus its verified capabilities (ANA-198 / ANA-199).

- `load_agents()`            validated `AgentSpec` list (strict: a typo in the yaml is an error, not a silent default).
- `derive_profile_dict()` / `derive_connection_dict()`   what profiles.yaml / connections.yaml would say; those loaders use
  them to ADD an agent that exists here but not in their own yaml (adding an agent = one entry), and
  `check_consistency()` reports every field where an existing entry diverges (tests fail on any divergence).
- Capabilities (`supports`, `validated_on`) are what the orchestrator consults: `missing_capabilities(agent, role)`,
  `check_role(agent, role)`. An agent with `validated_on: null` supports nothing (prepared != validated).
Offline: nothing here runs a binary or touches the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.routing.registry import RegistryError, _parse_yaml
from config.paths import PACKAGE_ROOT

CATALOG_PATH = PACKAGE_ROOT / "config" / "agents.yaml"
CAPABILITIES = ("mcp", "headless", "usage_json", "readonly_sandbox", "worktree")
MCP_MODES = ("native", "env", "none")
ADAPTERS = ("hermes", "claude_code", "codex", "opencode")
STATUSES = ("available", "planned")
SNIPPET_FORMATS = ("hermes_yaml", "claude_json", "codex_toml")
# What a role needs from an agent before the orchestrator may hand it that role (ANA-199). The implementer WRITES
# files, so it needs a verified sandbox/permission switch to confine them; read-only roles are confined by the prompt
# contract + the adapter's text-only call.
ROLE_REQUIRES = {
    "orchestrator": (),
    "researcher": (),
    "reviewer": (),
    "implementer": ("readonly_sandbox",),
}
_BIN_ATTR = {"hermes": "hermes_bin", "claude_code": "claude_bin", "codex": "codex_bin", "opencode": "opencode_bin"}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class AgentCatalogError(ValueError):
    pass


class CapabilityError(ValueError):
    """The chosen agent lacks a capability the role needs. `reason_code` is machine-readable."""

    def __init__(self, agent: str, role: str, missing: tuple[str, ...]):
        self.agent, self.role, self.missing = agent, role, missing
        self.reason_code = f"capability_missing:{agent}:{role}:{'+'.join(missing)}"
        super().__init__(self.reason_code)


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    command: str
    env_keys: tuple[str, ...]
    detect_env_keys: tuple[str, ...]
    status: str
    docs_url: str | None
    mcp_snippet: str | None
    mcp_mode: str
    adapter: str | None
    bin_env: str | None
    model_provider: str | None
    supports: tuple[str, ...]
    validated_on: str | None
    description: str

    @property
    def validated(self) -> bool:
        return bool(self.validated_on)

    def effective_supports(self) -> tuple[str, ...]:
        """Prepared-but-not-validated agents support nothing."""
        return self.supports if self.validated else ()

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "command": self.command, "adapter": self.adapter,
                "mcp_mode": self.mcp_mode, "supports": list(self.effective_supports()),
                "validated_on": self.validated_on, "validated": self.validated}


def _names(raw, where, field, pattern) -> tuple[str, ...]:
    v = raw.get(field)
    if v is None:
        return ()
    if not isinstance(v, list) or not all(isinstance(k, str) and pattern.match(k) for k in v):
        raise AgentCatalogError(f"{where}: {field} must be a list of valid names")
    if len(set(v)) != len(v):
        raise AgentCatalogError(f"{where}: duplicate entries in {field}")
    return tuple(v)


def _opt_str(raw, where, field) -> str | None:
    v = raw.get(field)
    if v is not None and not isinstance(v, str):
        raise AgentCatalogError(f"{where}: {field} must be a string or null")
    return v


def _entry(raw, idx: int) -> AgentSpec:
    where = f"agents[{idx}]"
    if not isinstance(raw, dict):
        raise AgentCatalogError(f"{where}: must be a mapping")
    for f in ("id", "name", "command"):
        if not raw.get(f) or not isinstance(raw[f], str):
            raise AgentCatalogError(f"{where}: missing or invalid field {f!r}")
    aid = raw["id"]
    where = f"agent {aid!r}"
    if not _ID_RE.match(aid):
        raise AgentCatalogError(f"{where}: invalid id")
    status = raw.get("status") or "available"
    if status not in STATUSES:
        raise AgentCatalogError(f"{where}: status must be one of {STATUSES}")
    docs = _opt_str(raw, where, "docs_url")
    if docs is not None and not docs.startswith(("http://", "https://")):
        raise AgentCatalogError(f"{where}: docs_url must be an http(s) URL or null")
    snip = _opt_str(raw, where, "mcp_snippet")
    if snip is not None and snip not in SNIPPET_FORMATS:
        raise AgentCatalogError(f"{where}: mcp_snippet must be one of {SNIPPET_FORMATS} or null")
    mode = raw.get("mcp_mode") or "env"
    if mode not in MCP_MODES:
        raise AgentCatalogError(f"{where}: mcp_mode must be one of {MCP_MODES}")
    adapter = _opt_str(raw, where, "adapter")
    if adapter is not None and adapter not in ADAPTERS:
        raise AgentCatalogError(f"{where}: adapter must be one of {ADAPTERS} or null")
    bin_env = _opt_str(raw, where, "bin_env")
    if bin_env is not None and not _ENV_RE.match(bin_env):
        raise AgentCatalogError(f"{where}: bin_env must be an UPPER_CASE name")
    supports = raw.get("supports") or []
    if not isinstance(supports, list) or any(s not in CAPABILITIES for s in supports):
        raise AgentCatalogError(f"{where}: supports must be a list drawn from {CAPABILITIES}")
    if len(set(supports)) != len(supports):
        raise AgentCatalogError(f"{where}: duplicate entries in supports")
    if "headless" in supports and adapter is None:
        raise AgentCatalogError(f"{where}: 'headless' needs an adapter")
    return AgentSpec(
        id=aid, name=raw["name"], command=raw["command"],
        env_keys=_names(raw, where, "env_keys", _ENV_RE),
        detect_env_keys=_names(raw, where, "detect_env_keys", _ENV_RE),
        status=status, docs_url=docs, mcp_snippet=snip, mcp_mode=mode, adapter=adapter, bin_env=bin_env,
        model_provider=_opt_str(raw, where, "model_provider"), supports=tuple(supports),
        validated_on=_opt_str(raw, where, "validated_on"), description=str(raw.get("description") or ""))


def load_agents(path: Path | str | None = None) -> list[AgentSpec]:
    p = Path(path) if path is not None else CATALOG_PATH
    try:
        data = _parse_yaml(p.read_text(encoding="utf-8"))
    except RegistryError as e:
        raise AgentCatalogError(f"{p.name}: {e}") from e
    except OSError as e:
        raise AgentCatalogError(f"cannot read {p}: {e}") from e
    items = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise AgentCatalogError("top-level 'agents' list is required and must be non-empty")
    out, seen = [], set()
    for i, raw in enumerate(items):
        a = _entry(raw, i)
        if a.id in seen:
            raise AgentCatalogError(f"duplicate agent id {a.id!r}")
        seen.add(a.id)
        out.append(a)
    return out


def get_agent(agent_id: str | None, path: Path | str | None = None) -> AgentSpec | None:
    if not agent_id:
        return None
    return next((a for a in load_agents(path) if a.id == agent_id), None)


# ------------------------------------------------------------------------------------------ capabilities (ANA-199)
def missing_capabilities(agent: AgentSpec, role: str) -> tuple[str, ...]:
    need = ROLE_REQUIRES.get(role)
    if need is None:
        raise CapabilityError(agent.id, role, ("known_role",))
    have = set(agent.effective_supports())
    return tuple(c for c in need if c not in have)


def check_role(agent: AgentSpec, role: str) -> None:
    """Raise CapabilityError when `agent` cannot be given `role`."""
    miss = missing_capabilities(agent, role)
    if miss:
        raise CapabilityError(agent.id, role, miss)


def pick_launcher(agent: AgentSpec) -> str | None:
    """Launcher kind the orchestrator should use for this agent: 'agent_cli' (headless + usage) > 'terminal' > None."""
    sup = set(agent.effective_supports())
    if {"headless", "usage_json"} <= sup:
        return "agent_cli"
    if "mcp" in sup:
        return "terminal"
    return None


# ------------------------------------------------------------------------------------------ derivation / consistency
def derive_profile_dict(a: AgentSpec) -> dict:
    return {"id": a.id, "name": a.name, "kind": "agent", "command": a.command, "args": [],
            "env_keys": list(a.env_keys), "description": a.description}


def derive_connection_dict(a: AgentSpec) -> dict:
    return {"id": a.id, "type": "agent", "name": a.name, "command": a.command,
            "env_keys": list(a.detect_env_keys), "docs_url": a.docs_url, "status": a.status,
            "mcp_snippet": a.mcp_snippet}


def check_consistency(agents: list[AgentSpec] | None = None, profiles: dict | None = None,
                      connections: list | None = None) -> list[str]:
    """Human-readable divergences between agents.yaml and the other three views. Empty list = consistent.

    profiles/connections default to the on-disk yaml files WITHOUT the derived additions (the raw views)."""
    from app.terminals import mcp_inject
    from app.terminals.profiles import load_profiles
    from app.connections.catalog import load_catalog
    from config.agents import AgentsConfig
    agents = agents if agents is not None else load_agents()
    profiles = profiles if profiles is not None else load_profiles(derive=False)
    connections = connections if connections is not None else load_catalog(derive=False)
    conns = {c.id: c for c in connections}
    cfg = AgentsConfig()
    problems: list[str] = []
    for a in agents:
        p = profiles.get(a.id)
        if p is not None:
            if p.kind != "agent":
                problems.append(f"{a.id}: profile kind is {p.kind!r}, expected 'agent'")
            if p.command != a.command:
                problems.append(f"{a.id}: profile command {p.command!r} != catalog {a.command!r}")
            if tuple(p.env_keys) != a.env_keys:
                problems.append(f"{a.id}: profile env_keys {list(p.env_keys)} != catalog {list(a.env_keys)}")
            if mcp_inject.mode_for(p) != a.mcp_mode:
                problems.append(f"{a.id}: mcp_mode {a.mcp_mode!r} != mcp_inject {mcp_inject.mode_for(p)!r}")
        c = conns.get(a.id)
        if c is not None:
            if c.type != "agent":
                problems.append(f"{a.id}: connection type is {c.type!r}, expected 'agent'")
            if (c.command or "") != a.command:
                problems.append(f"{a.id}: connection command {c.command!r} != catalog {a.command!r}")
            if tuple(c.env_keys) != a.detect_env_keys:
                problems.append(f"{a.id}: connection env_keys {list(c.env_keys)} != catalog detect_env_keys")
            if c.status != a.status:
                problems.append(f"{a.id}: connection status {c.status!r} != catalog {a.status!r}")
            if c.mcp_snippet != a.mcp_snippet:
                problems.append(f"{a.id}: connection mcp_snippet {c.mcp_snippet!r} != catalog {a.mcp_snippet!r}")
            if c.docs_url != a.docs_url:
                problems.append(f"{a.id}: connection docs_url differs from catalog")
        if a.bin_env:
            attr = _BIN_ATTR.get(a.adapter or "")
            if attr is None or not hasattr(cfg, attr):
                problems.append(f"{a.id}: bin_env {a.bin_env} has no AgentsConfig field for adapter {a.adapter!r}")
    ids = {a.id for a in agents}
    for pid, p in profiles.items():
        if p.kind == "agent" and pid not in ids:
            problems.append(f"{pid}: agent profile missing from agents.yaml")
    for c in connections:
        if c.type == "agent" and c.id not in ids:
            problems.append(f"{c.id}: agent connection missing from agents.yaml")
    return problems
