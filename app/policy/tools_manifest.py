"""ANA-192: manifest of MCP tools (scope, risk, what enables each) + usage log. Source of truth for 'what can an agent do'.

`declared_tools()` reads app/mcp/server.py with `ast` (no import, no side effects) and returns every function
decorated with `@server.tool()`; tests assert it equals MANIFEST, so a tool cannot be added without being classified.
Profiles: `allowed_for_profile("restricted")` is the read-only subset; `default` = what the env flags enable.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "mcp" / "server.py"

MANIFEST = {
    "memory_search": {"scope": "read", "risk": "low", "enabled_by": "always"},
    "memory_search_baseline": {"scope": "read", "risk": "low", "enabled_by": "MG_MCP_TOOLSET=full"},
    "memory_search_graphify": {"scope": "read", "risk": "low", "enabled_by": "MG_MCP_TOOLSET=full"},
    "memory_search_graphify_jev": {"scope": "read", "risk": "low", "enabled_by": "MG_MCP_TOOLSET=full"},
    "memory_get_run": {"scope": "read", "risk": "low", "enabled_by": "MG_MCP_TOOLSET=full"},
    "memory_stats": {"scope": "read", "risk": "low", "enabled_by": "MG_MCP_TOOLSET=full"},
    "memory_benchmark": {"scope": "compute", "risk": "medium", "enabled_by": "MG_MCP_TOOLSET=full"},
    "memory_save": {"scope": "write", "risk": "medium", "enabled_by": "MG_MCP_SAVE=1"},
    "memory_feedback": {"scope": "write", "risk": "low", "enabled_by": "MG_MCP_SAVE=1"},
}
PROFILES = {"restricted": ("memory_search",), "readonly": tuple(k for k, v in MANIFEST.items() if v["scope"] == "read")}


def declared_tools(path: Path = SERVER) -> set[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                f = d.func if isinstance(d, ast.Call) else d
                if isinstance(f, ast.Attribute) and f.attr == "tool":
                    found.add(node.name)
    return found


def allowed_for_profile(profile: str) -> tuple[str, ...]:
    if profile in PROFILES:
        return PROFILES[profile]
    if profile == "default":
        return tuple(MANIFEST)
    raise KeyError(f"unknown tool profile {profile!r}")


def is_allowed(tool: str, profile: str) -> bool:
    return tool in allowed_for_profile(profile)


def log_use(tool: str, profile: str = "default", allowed: bool = True, run_id: str | None = None) -> dict:
    """Append a usage line to the chained policy audit (argument values are NEVER logged)."""
    from app.policy.engine import audit
    return audit("tool_use", {"actor": profile, "action": "exec", "target": f"tool:{tool}", "rule": "tool_manifest",
                              "allowed": allowed, "run_id": run_id, "scope": MANIFEST.get(tool, {}).get("scope")})


def active_profile() -> str:
    return os.environ.get("ANAMNESIA_TOOL_PROFILE", "default").strip().lower() or "default"
