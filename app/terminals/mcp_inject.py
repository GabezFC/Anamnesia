"""Injeta o servidor MCP `memory_gateway` em cada sessão de terminal, sem tocar na config global do usuário.

Mecanismo por CLI (só o que foi verificado com `<cli> --help`; AGENTS.md regra 6):
- claude  -> `--mcp-config <arquivo.json>` (verificado na Claude Code 2.1.x). NÃO usa `--strict-mcp-config`:
             os MCPs do usuário continuam valendo, o memory_gateway é somado a eles.
- demais  -> fallback documentado: nenhum arquivo global é editado; o PTY recebe MG_MCP_CONFIG (JSON no formato
             `mcpServers`), MG_MCP_COMMAND/MG_MCP_ARGS/MG_MCP_CWD e MEMORY_GATEWAY_URL para o usuário/CLI plugar.
             Codex (`-c mcp_servers...`), OpenCode (OPENCODE_CONFIG) e Gemini não estão instalados aqui, então
             não são ligados automaticamente (integração não testada não é suportada). Hermes não tem flag
             por invocação (só HERMES_HOME isolado, que perderia o login do usuário).
Opt-out: MG_TERMINAL_MCP=0 (ou `mcp:false` na criação da sessão). Os arquivos ficam em data/terminal_mcp/.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "data" / "terminal_mcp"
SERVER_NAME = "memory_gateway"
DEFAULT_URL = "http://127.0.0.1:8000"
_OFF = {"0", "false", "no", "off"}
NATIVE_FLAG = {"claude": "--mcp-config"}  # basename do executável -> flag verificada


def enabled(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get("MG_TERMINAL_MCP", "1")).strip().lower() not in _OFF


def project_python() -> str:
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        p = ROOT / rel
        if p.is_file():
            return str(p)
    return sys.executable


def _exe_key(profile) -> str:
    cmd = profile.windows_command or profile.command if sys.platform == "win32" else profile.command
    return re.sub(r"\.(exe|cmd|bat)$", "", Path(str(cmd)).name.lower())


def mode_for(profile) -> str:
    """native = arquivo injetado por flag verificada; env = só variáveis (fallback); none = shell/sem MCP."""
    if getattr(profile, "kind", "agent") != "agent":
        return "none"
    return "native" if _exe_key(profile) in NATIVE_FLAG else "env"


def is_default(profile, environ=None) -> bool:
    return enabled(environ) and mode_for(profile) != "none"


@dataclass
class McpInjection:
    enabled: bool = False
    mode: str = "off"            # off | native | env
    config_path: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    def public(self) -> dict:
        return {"enabled": self.enabled, "mode": self.mode, "server": SERVER_NAME if self.enabled else None}


def server_spec(scope: str, role: str | None, url: str, environ=None) -> dict:
    env = os.environ if environ is None else environ
    senv = {"MG_SCOPE": scope, "MEMORY_GATEWAY_URL": url,
            "MG_MCP_TOOLSET": env.get("MG_MCP_TOOLSET") or "minimal"}
    if role:
        senv["MG_AGENT_ROLE"] = role
    return {"command": project_python(), "args": ["-m", "app.mcp.server"], "cwd": str(ROOT), "env": senv}


def prepare(profile, session_key: str, scope: str, role: str | None = None, environ=None,
            want: bool | None = None, config_dir: Path | None = None) -> McpInjection:
    env = os.environ if environ is None else environ
    if want is False or not enabled(env) or mode_for(profile) == "none":
        return McpInjection()
    mode = mode_for(profile)
    url = env.get("MEMORY_GATEWAY_URL") or DEFAULT_URL
    spec = server_spec(scope, role, url, env)
    d = Path(config_dir) if config_dir else CONFIG_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{re.sub(r'[^A-Za-z0-9_-]', '', session_key)}.json"
    path.write_text(json.dumps({"mcpServers": {SERVER_NAME: spec}}, indent=2), encoding="utf-8")
    xenv = {"MEMORY_GATEWAY_URL": url, "MG_MCP_CONFIG": str(path), "MG_MCP_URL": url,
            "MG_MCP_COMMAND": spec["command"], "MG_MCP_ARGS": "-m app.mcp.server", "MG_MCP_CWD": str(ROOT)}
    args = [NATIVE_FLAG[_exe_key(profile)], str(path)] if mode == "native" else []
    return McpInjection(True, mode, str(path), args, xenv)


def cleanup(config_path: str | None) -> None:
    if config_path:
        try:
            os.remove(config_path)
        except OSError:
            pass
