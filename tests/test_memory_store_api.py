"""Fase 7: REST API + MCP tool gating for agent-saved context."""
from __future__ import annotations

import asyncio
import importlib
import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import memory_store as api_mod
from app.services.security import get_or_create_local_token


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    app = FastAPI()
    app.include_router(api_mod.router)
    token = get_or_create_local_token()
    authed = TestClient(app, client=("127.0.0.1", 5000), headers={"X-MG-Token": token})
    anon = TestClient(app, client=("127.0.0.1", 5000))
    remote = TestClient(app, client=("10.0.0.5", 5000), headers={"X-MG-Token": token})
    return authed, anon, remote, tmp_path / "home"


NOTE = {"title": "Decisão X", "content": "Usamos FTS5.", "tags": ["a"], "project": "gw", "source_agent": "codex"}


def test_crud_roundtrip(env):
    c, _, _, home = env
    r = c.post("/api/memory/notes", json=NOTE)
    assert r.status_code == 201
    nid = r.json()["id"]
    assert list((home / "data" / "saved_context").glob("decisao-x-*.md"))
    lst = c.get("/api/memory/notes").json()
    assert lst["count"] == 1 and "content" not in lst["notes"][0]
    assert c.get("/api/memory/notes", params={"project": "zzz"}).json()["count"] == 0
    got = c.get(f"/api/memory/notes/{nid}").json()
    assert got["content"] == "Usamos FTS5." and got["source_agent"] == "codex"
    assert c.delete(f"/api/memory/notes/{nid}").json() == {"deleted": nid}
    assert c.get(f"/api/memory/notes/{nid}").status_code == 404


def test_writes_require_token_and_loopback(env):
    c, anon, remote, home = env
    for cl in (anon, remote):
        assert cl.post("/api/memory/notes", json=NOTE).status_code == 403
        assert cl.post("/api/memory/forget", json={"confirm": True}).status_code == 403
        assert cl.get("/api/memory/export").status_code == 403
    nid = c.post("/api/memory/notes", json=NOTE).json()["id"]
    assert anon.delete(f"/api/memory/notes/{nid}").status_code == 403
    assert c.get(f"/api/memory/notes/{nid}").status_code == 200
    bad = TestClient(c.app, client=("127.0.0.1", 1), headers={"X-MG-Token": "nope"})
    assert bad.post("/api/memory/notes", json=NOTE).status_code == 403
    assert len(list((home / "data" / "saved_context").glob("*.md"))) == 1


def test_secret_size_and_validation_errors(env):
    c, *_ = env
    r = c.post("/api/memory/notes", json={**NOTE, "content": "k sk-abcdefghijklmnopqrstuvwx1234"})
    assert r.status_code == 422 and "segredo" in r.json()["detail"]
    assert c.post("/api/memory/notes", json={**NOTE, "content": "x" * (64 * 1024 + 1)}).status_code == 413
    assert c.post("/api/memory/notes", json={**NOTE, "title": ""}).status_code == 422
    assert c.get("/api/memory/notes").json()["count"] == 0


@pytest.mark.parametrize("bad", ["..%2F..%2Fetc%2Fpasswd", "zzzzzzzzzz", "%2E%2E"])
def test_path_traversal_ids(env, bad):
    c, *_ = env
    assert c.get(f"/api/memory/notes/{bad}").status_code in (400, 404)
    assert c.delete(f"/api/memory/notes/{bad}").status_code in (400, 404)


def test_export_and_forget(env):
    c, *_ = env
    c.post("/api/memory/notes", json=NOTE)
    c.post("/api/memory/notes", json={**NOTE, "title": "Y"})
    r = c.get("/api/memory/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == 2
    assert c.post("/api/memory/forget", json={}).status_code == 400
    assert c.post("/api/memory/forget", json={"confirm": False}).status_code == 400
    assert c.get("/api/memory/notes").json()["count"] == 2
    assert c.post("/api/memory/forget", json={"confirm": True}).json() == {"deleted": 2}
    assert c.get("/api/memory/notes").json()["count"] == 0


# ---- MCP ----------------------------------------------------------------------------------------

@pytest.fixture
def _restore_mcp():
    yield
    import os
    os.environ.pop("MG_MCP_SAVE", None)
    os.environ.pop("MG_MCP_TOOLSET", None)
    from app.mcp import server as mod
    importlib.reload(mod)


def _tools(monkeypatch, save=None, toolset=None):
    for k, v in (("MG_MCP_SAVE", save), ("MG_MCP_TOOLSET", toolset)):
        monkeypatch.delenv(k, raising=False)
        if v is not None:
            monkeypatch.setenv(k, v)
    from app.mcp import server as mod
    mod = importlib.reload(mod)
    return mod, {t.name for t in asyncio.run(mod.server.list_tools())}


def test_mcp_default_toolset_has_no_save(monkeypatch, _restore_mcp):
    _, names = _tools(monkeypatch)
    assert names == {"memory_search"}
    _, names = _tools(monkeypatch, save="0")
    assert names == {"memory_search"}
    _, names = _tools(monkeypatch, toolset="full")
    assert "memory_save" not in names


def test_mcp_save_tool_only_with_flag(monkeypatch, tmp_path, _restore_mcp):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    mod, names = _tools(monkeypatch, save="1")
    assert names == {"memory_search", "memory_save"}
    out = mod.memory_save("Fato MCP", "conteúdo via MCP", ["x"], "gw")
    assert "id" in out
    from app.memory_store.store import get_store
    n = get_store().get(out["id"])
    assert n.source_agent == "mcp" and n.title == "Fato MCP"
    err = mod.memory_save("Chave", "sk-abcdefghijklmnopqrstuvwx1234")
    assert "error" in err and "id" not in err
    assert len(get_store().list()) == 1
