"""Remover projeto: DELETE /api/projects/{id} desvincula, nunca apaga arquivos; índice mantido por padrão."""
from __future__ import annotations

import hashlib
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.api import workspace_io as wio
from app.terminals.projects import ProjectRegistry
from app.workspace_io import tasks

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN, "Origin": ORIGIN, "Referer": ORIGIN + "/"}


def snapshot(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        out[os.path.relpath(d, root) + "/"] = None
    return out


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.delenv("ANAMNESIA_PATH_MAP", raising=False)
    monkeypatch.delenv("MG_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    dirs = []
    for n in ("proj_a", "proj_b"):
        d = tmp_path / n
        (d / "src").mkdir(parents=True)
        (d / "README.md").write_text(f"# {n}\n")
        (d / "src" / "a.py").write_text("x = 1\n")
        dirs.append(d)
    db = tmp_path / "anamnesia.db"

    def make_client():
        app = FastAPI()
        app.include_router(ws_api.router)
        app.include_router(wio.router)
        reg = ProjectRegistry(db)
        app.dependency_overrides[ws_api.get_registry] = lambda: reg
        return TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    return type("E", (), dict(dirs=dirs, db=db, make_client=staticmethod(make_client)))


def add(c, name, d):
    r = c.post("/api/projects", headers=H, json={"name": name, "path": str(d)})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_remove_flow_persists_and_keeps_files(env):
    c = env.make_client()
    a, b = add(c, "A", env.dirs[0]), add(c, "B", env.dirs[1])
    before = snapshot(env.dirs[0])
    r = c.delete(f"/api/projects/{a}", headers=H)
    assert r.status_code == 200 and r.json() == {"removed": True, "id": a, "files_untouched": True,
                                                 "index_purged": False, "index_kept": True}
    assert [p["id"] for p in c.get("/api/projects").json()["projects"]] == [b]
    assert snapshot(env.dirs[0]) == before                                  # listagem + hashes idênticos
    c2 = env.make_client()                                                   # "reinício": nova instância, mesmo DB
    assert [p["id"] for p in c2.get("/api/projects").json()["projects"]] == [b]
    assert c2.get(f"/api/projects/{b}/files", headers=H).status_code == 200  # o outro projeto segue intacto


def test_missing_and_duplicate_removal(env):
    c = env.make_client()
    a = add(c, "A", env.dirs[0])
    assert c.delete("/api/projects/naoexiste", headers=H).status_code == 404
    assert c.delete(f"/api/projects/{a}", headers=H).status_code == 200
    r = c.delete(f"/api/projects/{a}", headers=H)                            # duplicada -> 404 documentado, nada muda
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert (env.dirs[0] / "README.md").exists()


def test_auth_required(env):
    c = env.make_client()
    a = add(c, "A", env.dirs[0])
    assert c.delete(f"/api/projects/{a}").status_code in (401, 403)
    assert c.delete(f"/api/projects/{a}", headers={"X-MG-Token": "errado", "Origin": ORIGIN}).status_code in (401, 403)
    assert c.delete(f"/api/projects/{a}", headers={"X-MG-Token": TOKEN, "Origin": "http://evil.example"}).status_code in (401, 403)
    assert [p["id"] for p in c.get("/api/projects").json()["projects"]] == [a]


def _init(c, pid):
    r = c.post("/api/workspace/io/initialize", headers=H, json={"project_id": pid, "dry_run": False})
    assert r.status_code == 202, r.text
    for _ in range(200):
        j = c.get(f"/api/workspace/io/jobs/{r.json()['job']['id']}").json()["job"]
        if j["state"] in ("done", "failed"):
            assert j["state"] == "done", j
            return
        time.sleep(0.05)
    raise AssertionError("job não terminou")


def test_index_kept_by_default_and_reused_on_reregister(env):
    c = env.make_client()
    a = add(c, "A", env.dirs[0])
    _init(c, a)
    assert tasks.index_path(a).exists()
    assert c.delete(f"/api/projects/{a}", headers=H).status_code == 200
    assert tasks.index_path(a).exists()                                      # padrão: índice MANTIDO
    assert add(c, "A de novo", env.dirs[0]) == a                             # id estável -> reaproveita o índice


def test_purge_index_is_opt_in_and_scoped(env):
    c = env.make_client()
    a, b = add(c, "A", env.dirs[0]), add(c, "B", env.dirs[1])
    _init(c, a)
    _init(c, b)
    before = snapshot(env.dirs[0])
    r = c.delete(f"/api/projects/{a}?purge_index=true", headers=H)
    assert r.status_code == 200 and r.json()["index_purged"] is True and r.json()["index_kept"] is False
    assert not tasks.index_path(a).exists() and tasks.index_path(b).exists()  # outro projeto intocado
    assert snapshot(env.dirs[0]) == before                                    # arquivos originais intactos


def test_stable_ids(env):
    c = env.make_client()
    a = add(c, "A", env.dirs[0])
    assert c.delete(f"/api/projects/{a}", headers=H).status_code == 200
    assert add(c, "outro nome", env.dirs[0]) == a
