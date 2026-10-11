"""MCP memory_gateway injetado por sessão + worktree/subagente (FakePtyBackend, sem processo real)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.terminals import mcp_inject
from app.terminals.backend import FakePtyBackend
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN}


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    for k in ("MG_HOST", "HOST", ws_api.ALLOW_REMOTE_ENV, "MG_TERMINAL_MCP"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(mcp_inject, "CONFIG_DIR", tmp_path / "mcpcfg")
    fake = FakePtyBackend()
    env = {"PATH": "/bin"}
    mgr = TerminalManager(backend=fake, max_sessions=5, environ=env)
    reg = ProjectRegistry(tmp_path / "a.db")
    exe = sys.executable
    profiles = {
        "shell": Profile(id="shell", name="Shell", command=exe, kind="shell"),
        "claude-code": Profile(id="claude-code", name="C", command=exe, windows_command=exe),
        "other": Profile(id="other", name="O", command=exe, windows_command=exe),
    }
    # basename do executável decide o modo; faz o "claude" apontar para um binário chamado claude
    fake_claude = tmp_path / ("claude.exe" if sys.platform == "win32" else "claude")
    profiles["claude-code"] = Profile(id="claude-code", name="C", command=str(fake_claude),
                                      windows_command=str(fake_claude))
    fake_claude.write_text("x")
    if sys.platform != "win32":
        fake_claude.chmod(0o755)
    app = FastAPI()
    app.include_router(ws_api.router)
    app.dependency_overrides[ws_api.get_manager] = lambda: mgr
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    app.dependency_overrides[ws_api.get_profiles] = lambda: profiles
    proj = tmp_path / "repo"
    proj.mkdir()
    def git(*a):
        subprocess.run(["git", *a], cwd=proj, check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-q", "-m", "i")
    client = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    r = client.post("/api/projects", json={"name": "repo", "path": str(proj)}, headers=H)
    assert r.status_code == 201, r.text
    yield type("C", (), dict(client=client, mgr=mgr, fake=fake, pid=r.json()["id"], env=env,
                             cfg=tmp_path / "mcpcfg", proj=proj))
    mgr.close_all()


def open_s(c, profile, **extra):
    r = c.client.post("/api/sessions", json={"project": c.pid, "profile": profile, **extra}, headers=H)
    return r


def test_claude_gets_mcp_config_flag_and_env(ctx):
    r = open_s(ctx, "claude-code")
    assert r.status_code == 201, r.text
    sess = r.json()["session"]
    assert sess["mcp"] == {"enabled": True, "mode": "native", "server": "memory_gateway"}
    h = ctx.fake.spawned[-1]
    assert h.argv[-2] == "--mcp-config" and "--strict-mcp-config" not in h.argv
    cfg = json.loads(open(h.argv[-1], encoding="utf-8").read())
    spec = cfg["mcpServers"]["memory_gateway"]
    assert spec["args"] == ["-m", "app.mcp.server"] and spec["cwd"] == str(mcp_inject.ROOT)
    assert spec["env"]["MG_MCP_TOOLSET"] == "minimal" and spec["env"]["MG_SCOPE"] == "repo"
    assert h.env["MEMORY_GATEWAY_URL"] == "http://127.0.0.1:8000" and h.env["MG_MCP_CONFIG"] == h.argv[-1]
    assert "ANTHROPIC_API_KEY" not in json.dumps(cfg)
    # arquivo é removido ao encerrar a sessão
    ctx.client.delete(f"/api/sessions/{r.json()['session_id']}", headers=H)
    assert not os.path.exists(h.argv[-1])


def test_other_agent_gets_env_fallback_only(ctx):
    r = open_s(ctx, "other")
    assert r.json()["session"]["mcp"]["mode"] == "env"
    h = ctx.fake.spawned[-1]
    assert "--mcp-config" not in h.argv and os.path.isfile(h.env["MG_MCP_CONFIG"])


def test_shell_gets_no_mcp(ctx):
    r = open_s(ctx, "shell")
    assert r.json()["session"]["mcp"]["enabled"] is False
    assert "MG_MCP_CONFIG" not in ctx.fake.spawned[-1].env


def test_optout_env_and_request(ctx, monkeypatch):
    assert open_s(ctx, "claude-code", mcp=False).json()["session"]["mcp"]["enabled"] is False
    ctx.env["MG_TERMINAL_MCP"] = "0"
    r = open_s(ctx, "claude-code")
    assert r.json()["session"]["mcp"]["enabled"] is False
    assert "--mcp-config" not in ctx.fake.spawned[-1].argv
    assert not list(ctx.cfg.glob("*.json")) if ctx.cfg.exists() else True


def test_profiles_expose_mcp_default(ctx, monkeypatch):
    d = {p["id"]: p for p in ctx.client.get("/api/profiles", headers=H).json()["profiles"]}
    assert d["claude-code"]["mcp_default"] is True and d["shell"]["mcp_default"] is False
    monkeypatch.setenv("MG_TERMINAL_MCP", "0")
    d = {p["id"]: p for p in ctx.client.get("/api/profiles", headers=H).json()["profiles"]}
    assert d["claude-code"]["mcp_default"] is False


def test_worktree_and_role(ctx):
    r = open_s(ctx, "claude-code", worktree=True, subagent_role="implementer")
    assert r.status_code == 201, r.text
    s = r.json()["session"]
    assert s["role"] == "implementer" and s["branch"].startswith("anamnesia/implementer-")
    assert s["worktree_id"] and os.path.isdir(s["cwd"]) and os.path.realpath(s["cwd"]) != os.path.realpath(ctx.proj)
    h = ctx.fake.spawned[-1]
    assert h.env["MG_AGENT_ROLE"] == "implementer" and h.cwd == s["cwd"]
    spec = json.loads(open(h.env["MG_MCP_CONFIG"], encoding="utf-8").read())["mcpServers"]["memory_gateway"]
    assert spec["env"]["MG_AGENT_ROLE"] == "implementer"
    # reutiliza um worktree existente por id
    r2 = open_s(ctx, "other", worktree=s["worktree_id"], subagent_role="reviewer")
    assert r2.status_code == 201 and r2.json()["session"]["cwd"] == s["cwd"]
    assert r2.json()["session"]["branch"] == s["branch"]


def test_invalid_role_and_missing_worktree(ctx):
    assert open_s(ctx, "other", subagent_role="hacker").status_code == 422
    assert open_s(ctx, "other", worktree="nope").status_code == 404
