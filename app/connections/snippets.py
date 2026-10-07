"""MCP config snippets. Only formats confirmed in this repo (integrations/ + README) are generated:

  * hermes_yaml : Hermes `mcp_servers` in config.yaml   (integrations/hermes/hermes_home/config.yaml)
  * claude_json : Claude Code `mcpServers` in .mcp.json (integrations/claude_code/mcp.json)
  * codex_toml  : Codex `[mcp_servers.*]` in config.toml (integrations/codex/config.toml.snippet)

Anything else returns {"status": "unverified", "note": ...} instead of a guess.
"""
from __future__ import annotations

import json

from app.connections.catalog import Connection

ROOT_PLACEHOLDER = "<PROJECT_ROOT>"
SERVER = "memory-gateway"


def _python(root: str) -> str:
    return f"{root}/.venv/Scripts/python.exe"


def hermes_yaml(root: str = ROOT_PLACEHOLDER) -> str:
    return (f"mcp_servers:\n  {SERVER}:\n    command: {_python(root)}\n    args:\n      - -m\n"
            f"      - app.mcp.server\n    cwd: {root}\n    connect_timeout: 60\n    timeout: 300\n"
            f"    enabled: true\n")


def claude_json(root: str = ROOT_PLACEHOLDER) -> str:
    cfg = {"mcpServers": {SERVER: {"command": _python(root), "args": ["-m", "app.mcp.server"], "cwd": root}}}
    return json.dumps(cfg, indent=2) + "\n"


def codex_toml(root: str = ROOT_PLACEHOLDER) -> str:
    return (f"[mcp_servers.{SERVER}]\ncommand = \"{_python(root)}\"\nargs = [\"-m\", \"app.mcp.server\"]\n"
            f"cwd = \"{root}\"\n")


_FORMATS = {
    "hermes_yaml": ("config.yaml (Hermes)", "yaml", hermes_yaml),
    "claude_json": (".mcp.json (Claude Code)", "json", claude_json),
    "codex_toml": ("config.toml (Codex)", "toml", codex_toml),
}
_NOTE = ("Substitua <PROJECT_ROOT> pelo caminho absoluto do checkout; no Linux/macOS o interpretador é "
         "<PROJECT_ROOT>/.venv/bin/python.")


def build_snippet(c: Connection, root: str = ROOT_PLACEHOLDER) -> dict:
    if c.type == "mcp":
        return {"status": "ok", "note": _NOTE,
                "snippets": {k: {"target": t, "language": lang, "content": fn(root)}
                             for k, (t, lang, fn) in _FORMATS.items()}}
    if c.mcp_snippet in _FORMATS:
        target, lang, fn = _FORMATS[c.mcp_snippet]
        return {"status": "ok", "format": c.mcp_snippet, "target": target, "language": lang,
                "content": fn(root), "note": _NOTE}
    if c.type == "agent":
        return {"status": "unverified",
                "note": f"Formato de configuração MCP do {c.name} não confirmado neste repositório."}
    return {"status": "unverified", "note": f"{c.name} não é um agente: não há snippet MCP aplicável."}
