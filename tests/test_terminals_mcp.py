"""Perfis do launcher PTY interno: MCP memory_gateway por padrão (sem rotas/UI; fixture de rotas morta removida)."""
from __future__ import annotations

import pytest  # noqa: F401


def test_profiles_expose_mcp_default(monkeypatch):
    from app.terminals import mcp_inject
    from app.terminals.profiles import load_profiles
    monkeypatch.setenv("MG_TERMINAL_MCP", "1")
    d = {p.id: p for p in load_profiles().values()}
    assert mcp_inject.is_default(d["claude-code"]) is True and mcp_inject.is_default(d["shell"]) is False
    monkeypatch.setenv("MG_TERMINAL_MCP", "0")
    d = {p.id: p for p in load_profiles().values()}
    assert mcp_inject.is_default(d["claude-code"]) is False
