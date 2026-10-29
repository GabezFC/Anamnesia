"""GET /api/projects/{id}/file — pré-visualização somente leitura (confinada, sem segredos)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.terminals.projects import ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.delenv("MG_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)


@pytest.fixture
def ctx(env, tmp_path):
    """App mínimo só com o router de workspace + registro de projetos temporário."""
    reg = ProjectRegistry(tmp_path / "anamnesia.db")
    app = FastAPI()
    app.include_router(ws_api.router)
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    proj_dir = tmp_path / "work"
    (proj_dir / "src").mkdir(parents=True)
    (proj_dir / "src" / "main.py").write_text("x")
    (proj_dir / "README.md").write_text("x")
    client = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    remote = TestClient(app, client=("192.168.1.50", 51234), base_url=ORIGIN)
    yield type("Ctx", (), dict(app=app, client=client, remote=remote, reg=reg, proj_dir=proj_dir))


def add_project(c):
    r = c.client.post("/api/projects", json={"name": "w", "path": str(c.proj_dir)}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _get(c, pid, path):
    return c.client.get(f"/api/projects/{pid}/file", params={"path": path}, headers=H)


def test_reads_text_file(ctx):
    (ctx.proj_dir / "README.md").write_bytes("olá\nmundo".encode("utf-8"))
    pid = add_project(ctx)
    r = _get(ctx, pid, "README.md")
    assert r.status_code == 200
    d = r.json()
    assert d["content"] == "olá\nmundo" and d["binary"] is False and d["truncated"] is False


def test_truncates_large_file(ctx):
    (ctx.proj_dir / "big.txt").write_text("a" * (200 * 1024 + 50))
    pid = add_project(ctx)
    d = _get(ctx, pid, "big.txt").json()
    assert d["truncated"] is True and len(d["content"]) == 200 * 1024


def test_binary_has_no_content(ctx):
    (ctx.proj_dir / "x.bin").write_bytes(b"\x00\x01\x02")
    pid = add_project(ctx)
    d = _get(ctx, pid, "x.bin").json()
    assert d["binary"] is True and d["content"] == ""


def test_blocks_secrets_and_escape(ctx):
    (ctx.proj_dir / ".env").write_text("KEY=segredo")
    pid = add_project(ctx)
    assert _get(ctx, pid, ".env").status_code == 403
    assert _get(ctx, pid, "../outside.txt").status_code == 403
    assert _get(ctx, pid, "nao-existe.txt").status_code == 404
    assert _get(ctx, pid, "src").status_code == 404  # diretório


def test_requires_local_token(ctx):
    pid = add_project(ctx)
    assert ctx.remote.get(f"/api/projects/{pid}/file", params={"path": "README.md"}, headers=H).status_code in (401, 403)
