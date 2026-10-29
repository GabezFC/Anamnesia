"""Central de Importação, Exportação e Inicialização: scanner, gitignore, jobs, tarefas e API.

Também garante que os endpoints de sessão interativa de terminal (REST + WebSocket) NÃO existem mais,
enquanto projetos/explorador de arquivos/perfil de inicialização continuam disponíveis.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.api import workspace_io as wio
from app.terminals.projects import ProjectRegistry
from app.workspace_io import gitignore as gi
from app.workspace_io import scanner
from app.workspace_io import tasks
from app.workspace_io.jobs import JobManager

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN, "Origin": ORIGIN, "Referer": ORIGIN + "/"}


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "anamnesia_home"))  # notas/índice isolados do dado real
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.delenv("MG_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)


@pytest.fixture
def ctx(env, tmp_path):
    proj_dir = tmp_path / "proj"
    (proj_dir / "src").mkdir(parents=True)
    (proj_dir / "src" / "main.py").write_text("print('oi')\n")
    (proj_dir / "README.md").write_text("# Projeto\n")
    (proj_dir / ".gitignore").write_text("segredo*\n*.log\n")
    (proj_dir / "segredo.env").write_text("KEY=1\n")
    (proj_dir / "app.log").write_text("x\n")
    (proj_dir / "foto.png").write_bytes(b"\x89PNG")
    (proj_dir / "node_modules").mkdir()
    (proj_dir / "node_modules" / "lib.js").write_text("x\n")
    (proj_dir / ".env").write_text("SECRET=1\n")
    (proj_dir / "grande.txt").write_text("x" * (6 * 1024 * 1024), encoding="utf-8")

    app = FastAPI()
    app.include_router(ws_api.router)
    app.include_router(wio.router)
    reg = ProjectRegistry(tmp_path / "anamnesia.db")
    pid = reg.add("Proj Teste", str(proj_dir)).id
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    client = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    yield type("Ctx", (), dict(app=app, client=client, reg=reg, pid=pid, proj_dir=proj_dir,
                               home=tmp_path / "anamnesia_home",
                               jm=wio.get_jobs()))


def wait_job(c, job, timeout=10.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/workspace/io/jobs/{job['id']}").json()["job"]
        if j["state"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError("job não terminou")


# ------------------------------------------------------------------ gitignore
def test_gitignore_semantics(tmp_path):
    g = gi.GitIgnore("", "node_modules/\n*.log\n!important.log\nbuild\n")
    assert gi.is_ignored([g], "node_modules/x/lib.js", False) is True
    assert gi.is_ignored([g], "a/b.log", False) is True
    assert gi.is_ignored([g], "a/important.log", False) is False
    assert gi.is_ignored([g], "build/main.py", False) is True      # sem / inicial: casa em qualquer nível
    assert gi.is_ignored([g], "src/main.py", False) is False


# ------------------------------------------------------------------ scanner
def test_scan_skips_secrets_binaries_gitignore_and_huge(ctx):
    scan = scanner.scan_project(ctx.proj_dir)
    rels = [f.rel for f in scan.files]
    assert "src/main.py" in rels and "README.md" in rels and ".gitignore" in rels
    assert "segredo.env" not in rels and ".env" not in rels
    assert "app.log" not in rels and "foto.png" not in rels
    assert "node_modules/lib.js" not in rels and "grande.txt" not in rels
    assert scan.skipped["segredo_por_nome"] >= 1  # .env; segredo.env cai antes no .gitignore
    assert scan.skipped["binario"] >= 1
    assert scan.skipped["gitignore"] >= 1
    assert scan.skipped["enorme"] >= 1
    assert scan.skipped["pasta_dependencia_ou_build"] >= 1
    assert scan.markers  # README.md/.gitignore presentes


# ------------------------------------------------------------------ jobs
def test_job_cancel_and_lifecycle():
    jm = JobManager()
    state = {"n": 0}

    def work(job):
        for _ in range(50):
            job.check()
            state["n"] += 1
            job.progress(state["n"], 50)
        return {"n": state["n"]}

    job = jm.submit("x", None, "teste", work, synchronous=True)
    assert job.state == "done" and job.result == {"n": 50}

    import threading
    import time
    started, release = threading.Event(), threading.Event()

    def slow(job):
        started.set()
        release.wait(5)          # segura o trabalho até o cancelamento ser pedido (determinístico)
        for i in range(1000):
            job.check()
            job.progress(i + 1, 1000)
        return {"ok": True}

    job2 = jm.submit("y", None, "longa", slow, synchronous=False)
    assert started.wait(5)
    assert jm.cancel(job2.id).cancel_requested is True
    release.set()
    for _ in range(500):
        if job2.state in ("cancelled", "failed", "done"):
            break
        time.sleep(0.01)
    assert job2.state == "cancelled"
    assert job2.result is None


# ------------------------------------------------------------------ initialize
def test_initialize_dry_run_and_apply_idempotent(ctx):
    r = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": True}, headers=H)
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert job["state"] == "done" and job["result"]["dry_run"] is True
    assert job["result"]["index"]["total_after"] >= 3

    # aplica
    r = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": False}, headers=H)
    assert r.status_code == 202, r.text   # aplicação = tarefa em segundo plano
    first = wait_job(ctx.client, r.json()["job"])["result"]
    assert first["index"]["total_after"] > 0
    # segunda passada incremental: nada muda
    r = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": False}, headers=H)
    second = wait_job(ctx.client, r.json()["job"])["result"]
    assert second["index"]["new"] == 0 and second["index"]["changed"] == 0


def test_initialize_requires_project_and_auth(ctx):
    assert ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid}).status_code == 403
    assert ctx.client.post("/api/workspace/io/initialize", json={"project_id": "zzz"}, headers=H).status_code == 404


def test_initialize_unmounted_path_in_docker(ctx, monkeypatch):
    monkeypatch.setattr(tasks, "in_docker", lambda: True)
    r = ctx.client.post("/api/workspace/io/initialize",
                        json={"project_id": ctx.pid, "dry_run": True, "summary_note": False}, headers=H)
    assert r.status_code == 200  # caminho real existe; só valida o contrato
    err = ctx.client.post("/api/workspace/io/initialize", json={"project_id": "zzz"}, headers=H)
    assert err.status_code == 404


# ------------------------------------------------------------------ import
def test_import_dry_run_and_apply_md_json(ctx):
    files = [
        {"name": "a.md", "content": "---\ntitle: Nota A\ntags: [x, y]\n---\n\nConteúdo A."},
        {"name": "b.json", "content": json.dumps([
            {"title": "Nota B", "content": "Conteúdo B", "tags": ["t"]},
            {"title": "Nota A", "content": "Conteúdo A."},  # duplicata exata da anterior
        ])},
        {"name": "c.md", "content": "import os\nKEY = 'sk-abcdef0123456789ABCDEF'\n"},  # segredo => inválida
        {"name": "d.txt", "content": "formato não suportado"},
    ]
    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": True, "source": "upload", "files": files}, headers=H)
    job = r.json()["job"]
    counts = job["result"]["counts"]
    assert counts["to_import"] == 2 and counts["duplicate"] == 1 and counts["invalid"] == 2
    st = {row["status"] for row in job["result"]["items"]}
    assert "importar" in st and "duplicado" in st and "invalido" in st

    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": False, "source": "upload", "files": files}, headers=H)
    job = wait_job(ctx.client, r.json()["job"])
    assert job["result"]["counts"]["imported"] == 2
    # reimportar: tudo duplicado (idempotente)
    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": False, "source": "upload", "files": files}, headers=H)
    job = wait_job(ctx.client, r.json()["job"])
    assert job["result"]["counts"]["imported"] == 0
    assert job["result"]["counts"]["duplicate"] >= 2


def test_import_from_project_path_skips_secrets(ctx):
    d = ctx.proj_dir / "memorias"
    d.mkdir()
    (d / "n1.md").write_text("# Nota Path 1\n\nCorpo.")
    (d / "bad.env").write_text("X=1")
    (d / "bin.py").write_bytes(b"\x00\x01")
    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": True, "source": "path", "path": "memorias"}, headers=H)
    job = r.json()["job"]
    counts = job["result"]["counts"]
    assert counts["to_import"] == 1
    # escape de caminho
    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": True, "source": "path", "path": "../fora"}, headers=H)
    assert r.status_code in (403, 422)


def test_import_validation_errors(ctx):
    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": True, "source": "upload", "files": []}, headers=H)
    assert r.status_code == 422
    r = ctx.client.post("/api/workspace/io/import",
                        json={"project_id": ctx.pid, "dry_run": True, "source": "upload",
                              "files": [{"name": "x.json", "content": "{quebrado"}]}, headers=H)
    job = r.json()["job"]
    assert job["result"]["counts"]["invalid"] == 1


# ------------------------------------------------------------------ export
def test_export_memories_json_redacts_secrets(ctx, monkeypatch):
    # prepara: duas notas, uma com segredo
    from app.memory_store.store import SavedContextStore, saved_context_dir
    store = SavedContextStore(saved_context_dir(), rate_per_min=0)
    store.save("Nota ok", "conteúdo comum", ["t"], "Proj Teste", None, "untrusted")
    # o detector bloqueia a gravação normal; só a FIXTURE o contorna (simula nota legada/editada à mão no disco)
    import app.memory_store.store as store_mod
    monkeypatch.setattr(store_mod, "scan_secrets", lambda *a, **k: [])
    store.save("Nota segredo", "token = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCDEF'", ["t"], "Proj Teste", None, "untrusted")
    monkeypatch.undo()
    monkeypatch.setenv("ANAMNESIA_HOME", str(ctx.home))
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    r = ctx.client.post("/api/workspace/io/export",
                        json={"project_id": ctx.pid, "kind": "memories", "format": "json",
                              "scope": "project", "dry_run": True}, headers=H)
    job = r.json()["job"]
    assert job["result"]["records"] >= 2
    assert job["result"]["secrets_included"] is False

    r = ctx.client.post("/api/workspace/io/export",
                        json={"project_id": ctx.pid, "kind": "memories", "format": "json",
                              "scope": "project", "dry_run": False}, headers=H)
    job = wait_job(ctx.client, r.json()["job"])
    assert job["result"]["filename"].endswith(".json")
    dl = ctx.client.get(f"/api/workspace/io/jobs/{job['id']}/download", headers=H)
    assert dl.status_code == 200
    data = json.loads(dl.content.decode("utf-8"))
    contents = " ".join(d["content"] for d in data["data"])
    assert "ghp_" not in contents and "REDATADO" in contents


def test_export_csv_and_md_and_metadata(ctx):
    for fmt in ("csv", "md"):
        r = ctx.client.post("/api/workspace/io/export",
                            json={"project_id": ctx.pid, "kind": "metadata", "format": fmt,
                                  "scope": "all", "dry_run": False}, headers=H)
        job = wait_job(ctx.client, r.json()["job"])
        assert job["result"]["filename"].endswith("." + fmt)
        dl = ctx.client.get(f"/api/workspace/io/jobs/{job['id']}/download", headers=H)
        assert dl.status_code == 200 and dl.content


def test_export_index_requires_initialized_project(ctx):
    r = ctx.client.post("/api/workspace/io/export",
                        json={"project_id": ctx.pid, "kind": "index", "format": "md",
                              "scope": "project", "dry_run": False}, headers=H)
    assert r.status_code == 409  # sem índice ainda
    assert r.json()["error"]["code"] == "no_index"
    r = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": False}, headers=H)
    wait_job(ctx.client, r.json()["job"])
    r = ctx.client.post("/api/workspace/io/export",
                        json={"project_id": ctx.pid, "kind": "index", "format": "md",
                              "scope": "project", "dry_run": False}, headers=H)
    job = wait_job(ctx.client, r.json()["job"])
    assert job["result"]["filename"].endswith(".md")


def test_export_requires_auth_and_valid_kind(ctx):
    assert ctx.client.post("/api/workspace/io/export",
                           json={"project_id": ctx.pid, "kind": "memories"}).status_code == 403
    r = ctx.client.post("/api/workspace/io/export",
                        json={"project_id": ctx.pid, "kind": "tudo", "dry_run": True}, headers=H)
    assert r.status_code == 422


# ------------------------------------------------------------------ jobs API + terminal ausente
def test_jobs_list_and_unknown_job(ctx):
    ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": True}, headers=H)
    assert ctx.client.get("/api/workspace/io/jobs").status_code == 200
    assert ctx.client.get("/api/workspace/io/jobs/nao-existe").status_code == 404


def test_interactive_session_endpoints_are_gone(ctx):
    c = ctx.client
    assert c.get("/api/sessions", headers=H).status_code in (404, 405)
    assert c.get("/api/profiles").status_code in (404, 405)
    assert c.post("/api/sessions", json={"project": ctx.pid, "profile": "shell"}, headers=H).status_code in (404, 405)


def test_project_explorer_and_initialize_endpoints_remain(ctx):
    c = ctx.client
    assert c.get("/api/projects").status_code == 200
    assert c.get(f"/api/projects/{ctx.pid}/files", headers=H).status_code == 200
    # contrato legado preservado: 200 com vault configurado; 409 gateway_not_configured sem vault (nunca 500)
    r = c.post(f"/api/projects/{ctx.pid}/initialize", json={"dry_run": True}, headers=H)
    assert r.status_code in (200, 409), r.text
    if r.status_code == 409:
        assert r.json()["error"]["code"] == "gateway_not_configured"


# ------------------------------------------------------------------ status / histórico / validações de borda
def test_status_reports_availability_and_real_index(ctx):
    r = ctx.client.get(f"/api/workspace/io/status?project_id={ctx.pid}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["availability"]["available"] is True and d["project"]["name"] == "Proj Teste"
    assert d["index"] == {"indexed": False, "files": 0, "secret_files": 0, "updated": None}   # sem índice: nada inventado
    j = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": False}, headers=H).json()["job"]
    wait_job(ctx.client, j)
    d = ctx.client.get(f"/api/workspace/io/status?project_id={ctx.pid}").json()
    assert d["index"]["indexed"] is True and d["index"]["files"] >= 3 and d["index"]["updated"]
    assert ctx.client.get("/api/workspace/io/status").status_code == 422
    assert ctx.client.get("/api/workspace/io/status?project_id=zzz").status_code == 404


def test_history_persists_only_applied_operations(ctx):
    ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": True}, headers=H)  # prévia
    assert ctx.client.get(f"/api/workspace/io/history?project_id={ctx.pid}").json()["history"] == []
    j = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid, "dry_run": False}, headers=H).json()["job"]
    wait_job(ctx.client, j)
    h = ctx.client.get(f"/api/workspace/io/history?project_id={ctx.pid}").json()["history"]
    assert len(h) == 1 and h[0]["kind"] == "initialize" and h[0]["state"] == "done" and "indexados" in h[0]["summary"]
    assert tasks.history_path().exists() and tasks.history_path().is_relative_to(ctx.home)   # persistente em disco


def test_unavailable_path_windows_in_container_and_missing_dir(ctx, monkeypatch, tmp_path):
    (tmp_path / "nao_existe").mkdir()
    gone = ctx.reg.add("Sumiu", str(tmp_path / "nao_existe")).id
    (tmp_path / "nao_existe").rmdir()          # a pasta some depois do cadastro (volume desmontado, HD removido)
    r = ctx.client.post("/api/workspace/io/initialize", json={"project_id": gone}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "path_unavailable"
    st = ctx.client.get(f"/api/workspace/io/status?project_id={gone}").json()
    assert st["availability"]["available"] is False
    # Docker + caminho do Windows: não finge acesso, explica o volume
    monkeypatch.setattr(tasks, "in_docker", lambda: True)
    monkeypatch.setattr(tasks.os, "name", "posix")
    a = tasks.project_availability("D:/projetos/x/proj")
    assert a["available"] is False and "contêiner" in a["reason"] and "volume" in a["hint"]


def test_unreadable_dir_is_reported(ctx, monkeypatch):
    monkeypatch.setattr(tasks.os, "access", lambda *a, **k: False)
    r = ctx.client.post("/api/workspace/io/initialize", json={"project_id": ctx.pid}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "path_unreadable"


def test_import_missing_path_empty_file_and_special_names(ctx):
    r = ctx.client.post("/api/workspace/io/import", json={"project_id": ctx.pid, "source": "path", "path": "nada/aqui"}, headers=H)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = ctx.client.post("/api/workspace/io/import", json={"project_id": ctx.pid, "source": "path", "path": "../fora"}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "path_escape"
    files = [{"name": "vazio.md", "content": ""},
             {"name": "../../evil ç ã #1 [x].md", "content": "# Título ç\n\nCorpo com acentuação."}]
    r = ctx.client.post("/api/workspace/io/import", json={"dry_run": True, "files": files}, headers=H)
    assert r.status_code == 200, r.text
    rows = {x["file"]: x for x in r.json()["job"]["result"]["items"]}
    assert rows["vazio.md"]["status"] == "invalido"
    sp = rows["evil ç ã #1 [x].md"]          # nome sanitizado: nenhum componente de diretório sobrevive
    assert sp["status"] == "importar" and sp["title"] == "Título ç"
