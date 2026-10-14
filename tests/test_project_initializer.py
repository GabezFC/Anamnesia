"""Inicializador de projeto (botão 'Inicializar Anamnésia'): criação só do que falta, idempotência, erros, API."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.services import project_initializer as pi
from app.terminals.projects import ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN}


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def env(vault):
    return {"MEMORY_GATEWAY_VAULT": str(vault)}


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    return p


def manifest_paths():
    return [r.path for r in pi.load_manifest() if r.kind == "file" and r.scope == "project"]


def vault_paths():
    return [r.path for r in pi.load_manifest() if r.kind == "file" and r.scope == "vault"]


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_empty_project_creates_everything(proj, env):
    rep = pi.initialize(proj, "p", environ=env)
    assert rep.ok and not rep.existing and not rep.already_configured
    assert set(manifest_paths()) <= set(rep.created)
    for rel in manifest_paths():
        assert (proj / rel).is_file()
    assert {"vault:" + p for p in vault_paths()} <= set(rep.created)


def test_generated_files_reference_vault_without_copying_it(proj, env, vault):
    (vault / "nota.md").write_text("segredo-do-vault")
    pi.initialize(proj, "p", environ=env)
    gw = json.loads((proj / ".anamnesia" / "gateway.json").read_text(encoding="utf-8"))
    assert gw["vault"]["path"] == str(vault.resolve()) and "write_rules" in gw["vault"]
    mcp = json.loads((proj / ".mcp.json").read_text(encoding="utf-8"))
    assert "memory_gateway" in mcp["mcpServers"]
    assert "segredo-do-vault" not in b"".join(snapshot(proj).values()).decode("utf-8")
    assert not list(proj.rglob("nota.md"))
    assert (vault / "nota.md").read_text() == "segredo-do-vault"   # nota existente do vault intocada


def test_already_configured_changes_nothing(proj, env):
    pi.initialize(proj, "p", environ=env)
    before = snapshot(proj)
    rep = pi.initialize(proj, "p", environ=env)
    assert rep.already_configured and not rep.created and rep.ok
    assert snapshot(proj) == before


def test_partial_creates_only_missing_and_keeps_user_content(proj, env):
    (proj / "AGENTS.md").write_text("MEU CONTEUDO", encoding="utf-8")
    rep = pi.initialize(proj, "p", environ=env)
    assert "AGENTS.md" in rep.existing and "AGENTS.md" not in rep.created
    assert (proj / "AGENTS.md").read_text(encoding="utf-8") == "MEU CONTEUDO"
    assert ".mcp.json" in rep.created


def test_deleted_file_is_recreated_alone(proj, env):
    pi.initialize(proj, "p", environ=env)
    (proj / "CLAUDE.md").unlink()
    (proj / "AGENTS.md").write_text("editado", encoding="utf-8")
    before = snapshot(proj)
    rep = pi.initialize(proj, "p", environ=env)
    assert rep.created == ["CLAUDE.md"]
    after = snapshot(proj)
    assert {k: v for k, v in after.items() if k != "CLAUDE.md"} == before


def test_repeated_runs_no_duplicates(proj, env):
    pi.initialize(proj, "p", environ=env)
    names = sorted(snapshot(proj))
    vnames = sorted(snapshot(Path(env["MEMORY_GATEWAY_VAULT"])))
    for _ in range(4):
        assert pi.initialize(proj, "p", environ=env).created == []
    assert sorted(snapshot(proj)) == names
    assert sorted(snapshot(Path(env["MEMORY_GATEWAY_VAULT"]))) == vnames


def test_dry_run_writes_nothing(proj, env):
    rep = pi.initialize(proj, "p", dry_run=True, environ=env)
    assert rep.created and not list(proj.iterdir())


def test_gateway_not_configured_creates_nothing(proj, tmp_path):
    for e in ({}, {"MEMORY_GATEWAY_VAULT": str(tmp_path / "nao-existe")}):
        with pytest.raises(pi.InitError) as ei:
            pi.initialize(proj, "p", environ=e)
        assert ei.value.code == "gateway_not_configured"
    assert not list(proj.iterdir())


def test_missing_project_dir(tmp_path, env):
    with pytest.raises(pi.InitError) as ei:
        pi.initialize(tmp_path / "nada", "p", environ=env)
    assert ei.value.code == "project_invalid"


def test_unwritable_project_is_reported(proj, env, monkeypatch):
    monkeypatch.setattr(pi.os, "access", lambda *a, **k: False)
    with pytest.raises(pi.InitError) as ei:
        pi.initialize(proj, "p", environ=env)
    assert ei.value.code == "project_not_writable"


def test_per_file_failure_is_reported_and_others_continue(proj, env, monkeypatch):
    real_open = open

    def fake_open(path, mode="r", *a, **k):
        if str(path).endswith(".mcp.json") and "x" in mode:
            raise PermissionError(13, "Permission denied")
        return real_open(path, mode, *a, **k)
    monkeypatch.setattr("builtins.open", fake_open)
    rep = pi.initialize(proj, "p", environ=env)
    assert not rep.ok and [f["path"] for f in rep.failed] == [".mcp.json"]
    assert "negada" in rep.failed[0]["reason"]
    assert "AGENTS.md" in rep.created and "CLAUDE.md" in rep.created


def test_dir_where_file_expected_is_failure_not_overwrite(proj, env):
    (proj / "AGENTS.md").mkdir()
    rep = pi.initialize(proj, "p", environ=env)
    assert [f["path"] for f in rep.failed] == ["AGENTS.md"] and (proj / "AGENTS.md").is_dir()


@pytest.mark.skipif(sys.platform == "win32", reason="symlink exige privilégio no Windows")
def test_symlink_escape_refused(proj, env, tmp_path):
    out = tmp_path / "fora"
    out.mkdir()
    os.symlink(out, proj / ".anamnesia")
    rep = pi.initialize(proj, "p", environ=env)
    assert any(f["path"] == ".anamnesia/gateway.json" for f in rep.failed) or ".anamnesia" in rep.failed[0]["path"]
    assert not list(out.iterdir())


def test_manifest_is_the_single_source_extensible(proj, env, tmp_path):
    """Novo requisito = nova entrada no manifesto/template, sem mudar código."""
    tdir = tmp_path / "t"
    tdir.mkdir()
    (tdir / "x.tmpl").write_text("proj={{project_name}} vault={{vault_path}}", encoding="utf-8")
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"directories": [{"path": "docs/ia"}],
                             "files": [{"path": "docs/ia/x.txt", "template": "x.tmpl"}]}), encoding="utf-8")
    rep = pi.initialize(proj, "meu", environ=env, manifest_path=m, templates_dir=tdir)
    assert rep.created == ["docs/ia", "docs/ia/x.txt"]
    assert (proj / "docs/ia/x.txt").read_text().startswith("proj=meu vault=")


@pytest.mark.parametrize("bad", ["../x", "/abs", "C:/x", "a/../b", ""])
def test_manifest_rejects_unsafe_paths(tmp_path, bad):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"files": [{"path": bad, "template": "x"}]}), encoding="utf-8")
    with pytest.raises(pi.InitError):
        pi.load_manifest(m)


def test_unknown_placeholder_is_error(tmp_path):
    (tmp_path / "t.tmpl").write_text("{{nao_existe}}", encoding="utf-8")
    with pytest.raises(pi.InitError):
        pi.render_template("t.tmpl", {}, tmp_path)


def test_shipped_manifest_and_templates_are_consistent():
    for r in pi.load_manifest():
        if r.kind == "file":
            assert (pi.TEMPLATES_DIR / r.template).is_file(), r.template


# ------------------------------------------------------------------ API
@pytest.fixture
def api(tmp_path, proj, env, monkeypatch):
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reg = ProjectRegistry(tmp_path / "anamnesia.db")
    app = FastAPI()
    app.include_router(ws_api.router)
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    c = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    pid = c.post("/api/projects", json={"name": "p", "path": str(proj)}, headers=H).json()["id"]
    return c, pid, proj


def test_api_initialize_and_idempotent(api):
    c, pid, proj = api
    r = c.post(f"/api/projects/{pid}/initialize", json={}, headers=H)
    assert r.status_code == 200 and r.json()["created"] and r.json()["ok"]
    r2 = c.post(f"/api/projects/{pid}/initialize", headers=H).json()
    assert r2["already_configured"] and not r2["created"]


def test_api_requires_token_and_known_project(api):
    c, pid, _ = api
    assert c.post(f"/api/projects/{pid}/initialize").status_code == 403
    assert c.post("/api/projects/nope/initialize", headers=H).status_code == 404


def test_api_gateway_not_configured_is_409(api, monkeypatch):
    c, pid, proj = api
    monkeypatch.delenv("MEMORY_GATEWAY_VAULT", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    r = c.post(f"/api/projects/{pid}/initialize", headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "gateway_not_configured"
    assert not [p for p in proj.iterdir()]


def test_os_errors_are_explained_in_portuguese():
    import errno
    assert "Permissão de escrita negada" in pi.explain_os_error(PermissionError(errno.EACCES, "Access is denied"))
    assert "Sem espaço" in pi.explain_os_error(OSError(errno.ENOSPC, "No space left on device"))
    assert "somente leitura" in pi.explain_os_error(OSError(errno.EROFS, "Read-only file system"))


def test_api_error_payload_has_code_message_and_hint(api, monkeypatch):
    c, pid, _ = api
    monkeypatch.delenv("MEMORY_GATEWAY_VAULT", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    e = c.post(f"/api/projects/{pid}/initialize", headers=H).json()["error"]
    assert e["code"] == "gateway_not_configured" and e["message"] and "Configuração" in e["hint"]


# ------------------------------------------------------------------ arquivos-guia no vault
def test_vault_guide_files_created_with_expected_content(proj, env, vault):
    rep = pi.initialize(proj, "p", environ=env)
    for n in ("AGENTS.md", "CLAUDE.md", "HOME.md", "Sem título.base"):
        assert (vault / n).is_file() and "vault:" + n in rep.created
    assert "Tabela de roteamento" in (vault / "AGENTS.md").read_text(encoding="utf-8")
    assert "Tabela de roteamento" in (vault / "CLAUDE.md").read_text(encoding="utf-8")
    assert "# HOME" in (vault / "HOME.md").read_text(encoding="utf-8")
    assert "type: table" in (vault / "Sem título.base").read_text(encoding="utf-8")


def test_vault_templates_carry_no_personal_data():
    for n in ("vault-AGENTS.md.tmpl", "vault-CLAUDE.md.tmpl", "vault-HOME.md.tmpl"):
        txt = (pi.TEMPLATES_DIR / n).read_text(encoding="utf-8")
        for bad in ("fonse", "Norteia", "Cérebro_AI", "ai-memory"):
            assert bad not in txt, (n, bad)


def test_existing_vault_files_are_never_touched_and_deleted_one_is_recreated(proj, env, vault):
    (vault / "AGENTS.md").write_text("MEU AGENTS", encoding="utf-8")
    rep = pi.initialize(proj, "p", environ=env)
    assert "vault:AGENTS.md" in rep.existing and (vault / "AGENTS.md").read_text() == "MEU AGENTS"
    (vault / "HOME.md").unlink()
    (vault / "CLAUDE.md").write_text("editado", encoding="utf-8")
    rep2 = pi.initialize(proj, "p", environ=env)
    assert rep2.created == ["vault:HOME.md"]
    assert (vault / "CLAUDE.md").read_text() == "editado"


def test_vault_not_writable_reports_failures_but_project_files_still_created(proj, env, vault, monkeypatch):
    real = os.access
    monkeypatch.setattr(pi.os, "access", lambda p, m: False if Path(p) == vault.resolve() else real(p, m))
    rep = pi.initialize(proj, "p", environ=env)
    assert {f["path"] for f in rep.failed} >= {"vault:AGENTS.md", "vault:HOME.md"}
    assert all("Vault (" in f["reason"] for f in rep.failed)
    assert (proj / "AGENTS.md").is_file() and not (vault / "HOME.md").exists()


def test_dry_run_does_not_touch_vault(proj, env, vault):
    pi.initialize(proj, "p", dry_run=True, environ=env)
    assert not list(vault.iterdir())
