"""Guards added after review: nothing may be written inside the vault; Hermes adapter parses the real
usage-file format (captured from hermes 0.20.5) and marks unavailable metrics as None."""
import json
import subprocess
from pathlib import Path

import pytest

from app.adapters.agents import agents as agents_mod
from app.adapters.agents.agents import HermesAdapter
from app.services.graphify import GraphifyError, GraphifyService
from app.services.obsidian import ObsidianVault
from app.services.pricing import break_even


def test_graphify_mirror_inside_vault_is_refused(tiny_vault):
    vault = ObsidianVault(tiny_vault)
    svc = GraphifyService(vault, Path(tiny_vault) / "mirror")
    with pytest.raises(GraphifyError):
        svc.sync_mirror()


def test_graphify_mirror_outside_vault_copies_only(tiny_vault, tmp_path):
    vault = ObsidianVault(tiny_vault)
    before = vault.state_hash()
    svc = GraphifyService(vault, tmp_path / "mirror")
    stats = svc.sync_mirror()
    assert stats["files"] == len(before)
    assert vault.state_hash() == before


def test_vault_check_refuses_saving_inside_vault(tiny_vault, monkeypatch):
    from app.cli import main as cli
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tiny_vault))
    with pytest.raises(SystemExit) as exc:
        cli.main(["vault-check", "--save", str(Path(tiny_vault) / "state.json")])
    assert "READ ONLY" in str(exc.value)
    assert not (Path(tiny_vault) / "state.json").exists()


REAL_USAGE = {"estimated_cost_usd": 0.0, "cost_status": "unknown", "cost_source": "none", "input_tokens": 23476,
              "output_tokens": 200, "cache_read_tokens": 4, "cache_write_tokens": 0, "reasoning_tokens": 0,
              "total_tokens": 23680, "api_calls": 1, "model": "qwen3:8b", "provider": "custom",
              "session_id": "x", "completed": True, "failed": False, "service_tier": None}


def _fake_run(usage: dict | None, stdout: bytes = b"ok", rc: int = 0):
    def run(args, timeout, env=None, cwd=None, stdin=None):
        assert env and "HERMES_HOME" in env
        assert "-z" in args and "--usage-file" in args and "--reasoning" in args
        path = Path(args[args.index("--usage-file") + 1])
        if usage is not None:
            path.write_text(json.dumps(usage), encoding="utf-8")
        return subprocess.CompletedProcess(args, rc, stdout, b"")
    return run


def test_hermes_adapter_parses_usage_file(monkeypatch):
    monkeypatch.setattr(agents_mod, "_run", _fake_run(REAL_USAGE))
    g = HermesAdapter().generate("prompt")
    assert g.answer == "ok" and g.error is None
    assert (g.input_tokens, g.output_tokens, g.agent_tokens) == (23476 + 4, 200, 23680)
    assert g.agent_cost is None  # cost_status unknown -> unavailable, never 0-by-assumption
    assert g.model == "qwen3:8b"


def test_hermes_adapter_failure_reported(monkeypatch):
    failed = dict(REAL_USAGE, failed=True, input_tokens=None, output_tokens=None, total_tokens=None,
                  failure="context window too small")
    monkeypatch.setattr(agents_mod, "_run", _fake_run(failed, stdout=b"", rc=1))
    g = HermesAdapter().generate("prompt")
    assert g.error and g.input_tokens is None and g.agent_tokens is None


def test_break_even_unavailable_propagates():
    be = break_even({"context_tokens": 1000, "total_cost": None}, {"context_tokens": 250, "total_cost": 0.001})
    assert be["context_reduction_percent"] == 75.0
    assert be["net_cost_change"] is None


CLAUDE_JSON = {"result": "ok", "subtype": "success", "total_cost_usd": 0.007,
              "usage": {"input_tokens": 9, "output_tokens": 82}}


def test_claude_code_adapter_isolates_global_state(monkeypatch, tmp_path):
    """Regression (2026-09-24): a bare `claude -p` inherited ~14 global MCP servers (~385k input
    tokens on a trivial prompt, exceeding the 200k context) and cross-call project auto-memory.
    The adapter must pass an empty --strict-mcp-config, --no-session-persistence and disableMemory."""
    import subprocess as sp

    from app.adapters.agents import agents as agents_mod
    from app.adapters.agents.agents import ClaudeCodeAdapter

    captured = {}

    def fake_run(args, timeout, env=None, cwd=None, stdin=None):
        captured["args"] = args
        return sp.CompletedProcess(args, 0, json.dumps(CLAUDE_JSON).encode(), b"")

    monkeypatch.setattr(agents_mod, "_run", fake_run)
    adapter = ClaudeCodeAdapter()
    adapter._empty_mcp_config = tmp_path / "empty_mcp.json"
    g = adapter.generate("prompt")

    args = captured["args"]
    assert "--strict-mcp-config" in args
    assert "--no-session-persistence" in args
    assert '{"disableMemory":true}' in args
    mcp_path = Path(args[args.index("--mcp-config") + 1])
    assert json.loads(mcp_path.read_text(encoding="utf-8")) == {"mcpServers": {}}
    assert g.answer == "ok" and g.input_tokens == 9 and g.output_tokens == 82 and g.agent_cost == 0.007
