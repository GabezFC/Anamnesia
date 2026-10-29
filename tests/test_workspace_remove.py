"""Remover projeto: desvincula o cadastro, nunca a pasta; duplicada/inexistente -> 404 limpo; persiste; DOM do modal."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.terminals import path_map
from app.terminals.projects import ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN, "Origin": ORIGIN, "Referer": ORIGIN + "/"}
FRONT = Path(__file__).resolve().parent.parent / "frontend"
NODE = shutil.which("node")


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "cont"
    for n in ("alfa", "beta"):
        (root / n / "src").mkdir(parents=True)
        (root / n / "src" / "main.py").write_text("print(1)\n")
        (root / n / "README.md").write_text("# " + n + "\n")
    monkeypatch.setenv(path_map.ENV_MAP, f"C:/Users/YourUser/Projetos_AI={root}")
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("ANAMNESIA_PROJECT_GUARD", "off")
    db = tmp_path / "anamnesia.db"

    def make():
        app = FastAPI()
        app.include_router(ws_api.router)
        reg = ProjectRegistry(db)
        app.dependency_overrides[ws_api.get_registry] = lambda: reg
        return TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN), reg

    c, reg = make()
    return type("E", (), dict(c=c, reg=reg, root=root, make=staticmethod(make)))


def _snapshot(p: Path) -> dict:
    return {str(f.relative_to(p)): f.read_bytes() for f in sorted(p.rglob("*")) if f.is_file()}


def test_register_select_remove_duplicate_missing_folder_intact(env):
    c = env.c
    r = c.post("/api/projects", json={"name": "Alfa", "path": "C:/Users/YourUser/Projetos_AI/alfa"}, headers=H)
    assert r.status_code == 201, r.text
    a = r.json()
    b = c.post("/api/projects", json={"name": "Beta", "path": r"C:\Users\YourUser\Projetos_AI\beta"}, headers=H).json()
    ids = {p["id"] for p in c.get("/api/projects", headers=H).json()["projects"]}
    assert ids == {a["id"], b["id"]}
    assert c.get(f"/api/projects/{a['id']}/files", headers=H).status_code == 200  # "seleção" lista arquivos
    before = {n: _snapshot(env.root / n) for n in ("alfa", "beta")}

    r = c.delete(f"/api/projects/{a['id']}", headers=H)
    assert r.status_code == 200 and r.json()["removed"] and r.json()["files_untouched"]
    # só o alfa saiu; beta intacto e utilizável
    assert {p["id"] for p in c.get("/api/projects", headers=H).json()["projects"]} == {b["id"]}
    assert c.get(f"/api/projects/{b['id']}/files", headers=H).status_code == 200
    assert c.get(f"/api/projects/{a['id']}/files", headers=H).status_code == 404
    # duplicada e inexistente: 404 limpo, nada muda
    for pid in (a["id"], "nao-existe"):
        d = c.delete(f"/api/projects/{pid}", headers=H)
        assert d.status_code == 404 and d.json()["error"]["code"] == "not_found"
    assert {p["id"] for p in c.get("/api/projects", headers=H).json()["projects"]} == {b["id"]}
    # pasta física e conteúdo intactos (inclusive com purge_index)
    assert c.delete(f"/api/projects/{b['id']}?purge_index=true", headers=H).status_code == 200
    assert {n: _snapshot(env.root / n) for n in ("alfa", "beta")} == before
    assert c.get("/api/projects", headers=H).json()["projects"] == []


def test_removal_persists_after_restart(env):
    a = env.c.post("/api/projects", json={"name": "Alfa", "path": "C:/Users/YourUser/Projetos_AI/alfa"}, headers=H).json()
    b = env.c.post("/api/projects", json={"name": "Beta", "path": "C:/Users/YourUser/Projetos_AI/beta"}, headers=H).json()
    assert env.c.delete(f"/api/projects/{a['id']}", headers=H).status_code == 200
    c2, _ = env.make()  # novo registro sobre o mesmo banco = reinício
    assert [p["id"] for p in c2.get("/api/projects", headers=H).json()["projects"]] == [b["id"]]


def test_remove_requires_local_write(env):
    a = env.c.post("/api/projects", json={"name": "Alfa", "path": "C:/Users/YourUser/Projetos_AI/alfa"}, headers=H).json()
    assert env.c.delete(f"/api/projects/{a['id']}").status_code in (401, 403)  # sem token/origem
    assert len(env.c.get("/api/projects", headers=H).json()["projects"]) == 1


def test_register_errors_are_specific(env):
    c = env.c
    r = c.post("/api/projects", json={"name": "X", "path": "D:/Outro/lugar"}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "path_not_mapped" and r.json()["error"]["roots"]
    r = c.post("/api/projects", json={"name": "X", "path": "C:/Users/YourUser/Projetos_AI/nao_existe"}, headers=H)
    assert r.status_code == 404 and r.json()["error"]["code"] == "path_not_found"
    r = c.post("/api/projects", json={"name": "X", "path": "C:/Users/YourUser/Projetos_AI/../Windows"}, headers=H)
    assert r.status_code in (403, 422) and r.json()["error"]["code"] in ("path_not_mapped", "path_escape", "path_invalid")
    assert c.get("/api/workspace/roots", headers=H).json()["roots"]


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_remove_button_and_modal_dom():
    """workspace.js: botão Remover com aria-label e modal com nome/caminho/cancelar/confirmar (render real via node)."""
    code = """
    globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
    globalThis.window = globalThis; globalThis.addEventListener = () => {};
    globalThis.document = { documentElement: { setAttribute() {} }, addEventListener() {}, activeElement: null };
    const md = await import('file:///%s');
    md.mockProjects.length = 0;
    md.mockProjects.push({ id: 'p1', name: 'Meu &lt;b&gt;Proj&lt;/b&gt;', path: 'C:/Users/YourUser/Projetos_AI/x', files: 0 });
    const w = await import('file:///%s');
    const live = await import('file:///%s');
    console.log(JSON.stringify({ html: w.render(), fmt: typeof live.refreshWorkspace }));
    """ % ((FRONT / "js/mock-data.js").as_posix(), (FRONT / "js/pages/workspace.js").as_posix(),
           (FRONT / "js/live.js").as_posix())
    r = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    h = out["html"]
    assert 'data-action="remove-project"' in h and 'data-project-id="p1"' in h
    assert "Remover projeto Meu &lt;b&gt;Proj&lt;/b&gt;" in h and "<b>Proj</b>" not in h and "&amp;lt;" not in h
    assert "rm-modal" not in h  # fechado por padrão: cancelar/abrir não altera nada
    assert out["fmt"] == "function"


def test_live_imports_fmttime():
    src = (FRONT / "js/live.js").read_text(encoding="utf-8")
    assert "import { fmtTime } from './format.js'" in src
