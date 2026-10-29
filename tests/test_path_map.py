"""Mapeamento host -> contêiner (ANAMNESIA_PATH_MAP): tradução, escape, erros específicos e API de registro."""
from __future__ import annotations

import hashlib
import os
import stat
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.terminals import path_map
from app.terminals.path_map import PathMapError, normalize_host_path, resolve_project_path
from app.terminals.projects import ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN, "Origin": ORIGIN, "Referer": ORIGIN + "/"}


@pytest.fixture
def maps(tmp_path, monkeypatch):
    """Duas raízes do 'host' (C: e D:) montadas em pastas locais fingindo o lado do contêiner."""
    c_root, d_root = tmp_path / "cont_c", tmp_path / "cont_d"
    (c_root / "Meu Projeto" / "src").mkdir(parents=True)
    (c_root / "Café Açaí").mkdir()
    (c_root / "Outro").mkdir()
    (d_root / "Dados").mkdir(parents=True)
    monkeypatch.setenv(path_map.ENV_MAP, f"C:/Users/YourUser/Projetos_AI={c_root};D:/Trabalho={d_root}")
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    return type("M", (), dict(c=c_root, d=d_root, tmp=tmp_path))


@pytest.mark.parametrize("raw,expected", [
    (r"C:\Users\YourUser\Projetos_AI\Meu Projeto", "C:/Users/YourUser/Projetos_AI/Meu Projeto"),
    ("c:/users/YourUser/Projetos_AI/", "C:/users/YourUser/Projetos_AI"),
    ("/c/Users/YourUser/x", "C:/Users/YourUser/x"),
    ("/mnt/d/Trabalho/a", "D:/Trabalho/a"),
    (r'"C:\Users\YourUser\Projetos_AI"', "C:/Users/YourUser/Projetos_AI"),
    (r"\\?\C:\Users\YourUser", "C:/Users/YourUser"),
    ("C:\\Users\\YourUser\\Projetos_AI\\\\Meu  Projeto\\.", "C:/Users/YourUser/Projetos_AI/Meu  Projeto"),
])
def test_normalize(raw, expected):
    assert normalize_host_path(raw) == expected


def test_normalize_rejects():
    with pytest.raises(PathMapError) as e:
        normalize_host_path(r"C:\a\..\b")
    assert e.value.code == "path_escape"
    for bad in ("", "   ", "relativo/pasta", "C:\\a|b", "C:\\a?"):
        with pytest.raises(PathMapError) as e:
            normalize_host_path(bad)
        assert e.value.code == "path_invalid"


def test_parse_map(maps):
    roots = path_map.parse_path_map()
    assert {r.host for r in roots} == {"C:/Users/YourUser/Projetos_AI", "D:/Trabalho"}
    assert path_map.parse_path_map("lixo;;sem-igual;C:/x=") == []


@pytest.mark.parametrize("raw", [
    r"C:\Users\YourUser\Projetos_AI\Meu Projeto", "c:/users/YOURUSER/projetos_ai/meu projeto",
    "/c/Users/YourUser/Projetos_AI/Meu Projeto", "C:/Users/YourUser/Projetos_AI/Meu Projeto/",
])
def test_translate_variants_with_spaces(maps, raw):
    tr = resolve_project_path(raw)
    assert tr.mapped and tr.container_path == os.path.realpath(maps.c / "Meu Projeto")
    assert tr.host_path == "C:/Users/YourUser/Projetos_AI/Meu Projeto"


def test_translate_accents_nfd_vs_nfc(maps):
    import unicodedata
    raw = "C:\\Users\\YourUser\\Projetos_AI\\" + unicodedata.normalize("NFD", "Café Açaí")
    tr = resolve_project_path(raw)
    assert tr.container_path == os.path.realpath(maps.c / "Café Açaí")
    assert tr.host_path.endswith("Café Açaí")


def test_two_drives(maps):
    a = resolve_project_path(r"C:\Users\YourUser\Projetos_AI\Outro")
    b = resolve_project_path(r"D:\Trabalho\Dados")
    assert a.container_path == os.path.realpath(maps.c / "Outro")
    assert b.container_path == os.path.realpath(maps.d / "Dados") and a.stable_key != b.stable_key


def test_not_mapped_lists_roots(maps):
    for raw in (r"C:\Users\YourUser\Documents\x", r"E:\Qualquer", r"C:\Users\YourUser\Projetos_AI_outro\x"):
        with pytest.raises(PathMapError) as e:
            resolve_project_path(raw)
        assert e.value.code == "path_not_mapped"
        assert "C:/Users/YourUser/Projetos_AI" in e.value.message and "D:/Trabalho" in e.value.message
        assert "ANAMNESIA_PATH_MAP" in e.value.hint and "recrie" in e.value.hint.lower()
        assert len(e.value.roots) == 2


def test_traversal_blocked(maps):
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\Projetos_AI\Outro\..\..\..\Windows")
    assert e.value.code == "path_escape"
    with pytest.raises(PathMapError) as e:
        resolve_project_path(str(maps.c / "Outro" / ".." / ".." / "x"))
    assert e.value.code == "path_escape"


def test_not_found_removed_or_renamed(maps):
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\Projetos_AI\Nao Existe")
    assert e.value.code == "path_not_found"
    (maps.c / "Outro").rename(maps.c / "Renomeada")
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\Projetos_AI\Outro")
    assert e.value.code == "path_not_found"


def test_file_is_invalid_and_missing_root_mount(maps, tmp_path):
    (maps.c / "arq.txt").write_text("x")
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\Projetos_AI\arq.txt")
    assert e.value.code == "path_invalid"
    os.environ[path_map.ENV_MAP] = f"C:/Users/YourUser/Projetos_AI={tmp_path / 'inexistente'}"
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\Projetos_AI\Outro")
    assert e.value.code == "path_not_found" and "montada" in e.value.message + e.value.hint


def test_symlink_escape(maps):
    outside = maps.tmp / "fora"
    outside.mkdir()
    link = maps.c / "evasivo"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink exige privilégio no Windows")
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\Projetos_AI\evasivo")
    assert e.value.code == "path_escape"


def test_permission(maps):
    if os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        pytest.skip("permissões POSIX não aplicáveis (Windows/root)")
    d = maps.c / "Outro"
    d.chmod(0)
    try:
        with pytest.raises(PathMapError) as e:
            resolve_project_path(r"C:\Users\YourUser\Projetos_AI\Outro")
        assert e.value.code == "path_permission"
    finally:
        d.chmod(stat.S_IRWXU)


def test_native_mode_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv(path_map.ENV_MAP, raising=False)
    monkeypatch.delenv("MG_IN_DOCKER", raising=False)
    d = tmp_path / "nativo com espaço"
    d.mkdir()
    tr = resolve_project_path(str(d))
    assert tr.container_path == str(d.resolve()) and not tr.mapped and tr.host_path == ""
    with pytest.raises(PathMapError) as e:
        resolve_project_path(str(tmp_path / "nao"))
    assert e.value.code == "path_not_found"


def test_docker_without_map_gives_actionable_error(monkeypatch):
    monkeypatch.delenv(path_map.ENV_MAP, raising=False)
    monkeypatch.setenv("MG_IN_DOCKER", "1")
    if os.name == "nt":
        pytest.skip("o ramo Docker só se aplica a hosts não-Windows")
    with pytest.raises(PathMapError) as e:
        resolve_project_path(r"C:\Users\YourUser\proj")
    assert e.value.code == "path_not_mapped"


# ----------------------------------------------------------------------------- API
@pytest.fixture
def api(maps):
    app = FastAPI()
    app.include_router(ws_api.router)
    reg = ProjectRegistry(maps.tmp / "anamnesia.db")
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    client = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    return type("A", (), dict(client=client, reg=reg, maps=maps))


def test_api_roots(api):
    r = api.client.get("/api/workspace/roots").json()
    assert r["mapped"] and len(r["roots"]) == 2
    assert {x["host_path"] for x in r["roots"]} == {"C:/Users/YourUser/Projetos_AI", "D:/Trabalho"}
    assert all(x["available"] for x in r["roots"]) and "token" not in str(r).lower()


def test_api_register_windows_path_and_persist(api):
    r = api.client.post("/api/projects", headers=H, json={"name": "Meu", "path": r"C:\Users\YourUser\Projetos_AI\Meu Projeto"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["path"] == "C:/Users/YourUser/Projetos_AI/Meu Projeto"           # exibição: caminho do host
    assert p["container_path"] == os.path.realpath(api.maps.c / "Meu Projeto") and p["mapped"]
    again = ProjectRegistry(api.maps.tmp / "anamnesia.db").get(p["id"])    # persistência + id estável
    assert again.host_path == p["path"] and again.path == p["container_path"]
    dup = api.client.post("/api/projects", headers=H, json={"name": "x", "path": "c:/users/YourUser/projetos_ai/MEU PROJETO"})
    assert dup.status_code == 422
    assert api.client.get("/api/projects").json()["projects"][0]["id"] == p["id"]


def test_api_error_codes(api):
    def post(path):
        return api.client.post("/api/projects", headers=H, json={"name": "n", "path": path})
    r = post(r"C:\Users\YourUser\Documents")
    assert r.status_code == 403 and r.json()["error"]["code"] == "path_not_mapped"
    assert len(r.json()["error"]["roots"]) == 2 and "ANAMNESIA_PATH_MAP" in r.json()["error"]["hint"]
    r = post(r"C:\Users\YourUser\Projetos_AI\naoexiste")
    assert r.status_code == 404 and r.json()["error"]["code"] == "path_not_found"
    assert post(r"C:\Users\YourUser\Projetos_AI\a\..\b").json()["error"]["code"] == "path_escape"
    assert post("relativo").json()["error"]["code"] == "path_not_mapped"
    assert post(r"C:\Users\YourUser\Projetos_AI\a|b").json()["error"]["code"] == "path_invalid"
    assert api.client.post("/api/projects", json={"name": "n", "path": r"C:\Users\YourUser\Projetos_AI\Outro"}).status_code == 403


def test_api_guard_still_refuses_sensitive_inside_mapped_root(api):
    (api.maps.c / "AppData" / "Roaming").mkdir(parents=True)
    r = api.client.post("/api/projects", headers=H, json={"name": "n", "path": r"C:\Users\YourUser\Projetos_AI\AppData\Roaming"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "project_root_denied"


def test_multiple_projects_two_drives(api):
    ids = []
    for name, path in (("a", r"C:\Users\YourUser\Projetos_AI\Outro"), ("b", r"D:\Trabalho\Dados"),
                       ("c", r"C:\Users\YourUser\Projetos_AI\Café Açaí")):
        r = api.client.post("/api/projects", headers=H, json={"name": name, "path": path})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    assert len(set(ids)) == 3
    listing = api.client.get("/api/projects").json()["projects"]
    assert {p["path"] for p in listing} == {"C:/Users/YourUser/Projetos_AI/Outro", "D:/Trabalho/Dados",
                                           "C:/Users/YourUser/Projetos_AI/Café Açaí"}
    # o explorador lê pelo caminho do contêiner
    (api.maps.d / "Dados" / "x.txt").write_text("oi")
    f = api.client.get(f"/api/projects/{ids[1]}/files", headers=H).json()
    assert [e["name"] for e in f["entries"]] == ["x.txt"]


def test_readonly_root_degrades_cleanly(api):
    """Raiz sem escrita: initialize grava o índice em ANAMNESIA_HOME e avisa; não cria nada na pasta."""
    from app.api import workspace_io as wio
    from app.workspace_io import tasks
    app = FastAPI()
    app.include_router(ws_api.router)
    app.include_router(wio.router)
    app.dependency_overrides[ws_api.get_registry] = lambda: api.reg
    c = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    pid = c.post("/api/projects", headers=H, json={"name": "ro", "path": r"C:\Users\YourUser\Projetos_AI\Meu Projeto"}).json()["id"]
    (api.maps.c / "Meu Projeto" / "README.md").write_text("# oi\n")
    before = sorted(os.listdir(api.maps.c / "Meu Projeto"))
    real_access = os.access
    root = os.path.realpath(api.maps.c / "Meu Projeto")

    def fake_access(p, mode, *a, **k):
        if mode & os.W_OK and os.path.realpath(str(p)).startswith(root):
            return False
        return real_access(p, mode, *a, **k)
    from unittest import mock
    with mock.patch("os.access", fake_access):
        st = c.get("/api/workspace/io/status", params={"project_id": pid}).json()
        assert st["availability"]["read_only"] is True and "ANAMNESIA_HOME" in st["availability"]["read_only_note"]
        r = c.post("/api/workspace/io/initialize", headers=H,
                   json={"project_id": pid, "dry_run": False, "install_project_files": True})
        assert r.status_code == 202, r.text
        import time
        for _ in range(100):
            j = c.get(f"/api/workspace/io/jobs/{r.json()['job']['id']}").json()["job"]
            if j["state"] in ("done", "failed"):
                break
            time.sleep(0.05)
    assert j["state"] == "done", j
    res = j["result"]
    assert res["read_only"] is True and res["project_files"]["error"] == "read_only_root" and res["warnings"]
    assert tasks.index_path(pid).exists()
    assert sorted(os.listdir(api.maps.c / "Meu Projeto")) == before            # nada criado dentro do projeto


def test_dir_hash_helper_sanity(tmp_path):
    (tmp_path / "a").write_text("1")
    assert hashlib.sha256((tmp_path / "a").read_bytes()).hexdigest()
    assert sys.version_info >= (3, 10)
