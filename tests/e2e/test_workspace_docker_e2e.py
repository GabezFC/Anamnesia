"""E2E REAL contra a instância Docker (mgtest, http://127.0.0.1:8010): projeto Windows ponta a ponta.

    ANAMNESIA_E2E_DOCKER=1 <python com playwright e pytest> -m pytest tests/e2e/test_workspace_docker_e2e.py -q

Cobre (via UI Playwright + API): Workspace sem terminal, raiz autorizada, registrar C:\\...\\_wio_ui_demo, navegar/selecionar,
arquivo sensível bloqueado, Inicializar (indexação), consulta que devolve o conteúdo, exportação sem segredos, escrita fora
do escopo negada (RO, traversal, path_not_mapped), Remover projeto (cancelar/confirmar) e hash da pasta host idêntico.
O token de escrita é lido do contêiner e NUNCA é impresso. Usa SOMENTE a pasta de dados falsos _wio_ui_demo.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ANAMNESIA_E2E_DOCKER") != "1", reason="set ANAMNESIA_E2E_DOCKER=1 (instância mgtest em :8010)")
pw = pytest.importorskip("playwright.sync_api")

BASE = os.environ.get("MG_E2E_BASE", "http://127.0.0.1:8010")
CONT = os.environ.get("MG_E2E_CONTAINER", "mgtest-anamnesia-1")
DEMO_ROOT_WIN = str(Path(os.environ.get("E2E_DEMO_DIR", "C:/Users/YourUser/Projetos_AI/_wio_ui_demo")).parent).replace("/", chr(92))
DEMO = Path(os.environ.get("E2E_DEMO_DIR", "C:/Users/YourUser/Projetos_AI/_wio_ui_demo"))
WIN = str(DEMO).replace("/", "\\")
NAME = "WIO UI Demo"
SHOTS = Path(os.environ.get("E2E_DOCKER_SHOTS", str(Path(__file__).resolve().parents[2] / "reports" / "workspace-docker-e2e")))


def _tree_hash() -> str:
    h = hashlib.sha256()
    for f in sorted(DEMO.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(DEMO).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def _token() -> str:
    r = subprocess.run(["docker", "exec", CONT, "sh", "-c", "grep '^MG_LOCAL_TOKEN=' /data/.env"], capture_output=True, text=True)
    return r.stdout.strip().split("=", 1)[1].strip().strip('"')


def _api(method: str, path: str, body=None):
    hdr = {"Content-Type": "application/json", "X-MG-Token": _token(), "Origin": BASE, "Referer": BASE + "/"}
    req = urllib.request.Request(BASE + path, method=method, headers=hdr, data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _j(method, path, body=None):
    s, b = _api(method, path, body)
    try:
        return s, json.loads(b)
    except ValueError:
        return s, {}


def _projects() -> list:
    return _j("GET", "/api/projects")[1].get("projects", [])


def _job(kind: str, body: dict) -> dict:
    s, r = _j("POST", f"/api/workspace/io/{kind}", body)
    assert s in (200, 202), (s, r)
    jid = (r.get("job") or r).get("id") or r.get("job_id")
    st: dict = {}
    for _ in range(60):
        st = _j("GET", f"/api/workspace/io/jobs/{jid}")[1]
        if (st.get("job") or st).get("status") not in ("queued", "running", "pending"):
            break
        time.sleep(0.5)
    return {"id": jid, "state": st}


@pytest.fixture(scope="module", autouse=True)
def live():
    try:
        urllib.request.urlopen(BASE + "/health", timeout=3)
    except OSError:
        pytest.skip("instância Docker :8010 indisponível")
    assert DEMO.is_dir(), f"pasta de demonstração ausente: {DEMO}"
    for p in _projects():
        if p["path"].rstrip("/").endswith("_wio_ui_demo"):
            _api("DELETE", f"/api/projects/{p['id']}")
    SHOTS.mkdir(parents=True, exist_ok=True)
    before = _tree_hash()
    yield before
    for p in _projects():
        if p["path"].rstrip("/").endswith("_wio_ui_demo"):
            _api("DELETE", f"/api/projects/{p['id']}")
    assert _tree_hash() == before, "a pasta do host mudou"


@pytest.fixture(scope="module")
def page_ctx():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        yield page, errs
        b.close()


def test_01_workspace_sem_terminal_e_registro_pela_ui(page_ctx):
    page, errs = page_ctx
    page.goto(BASE + "/#/workspace")
    page.wait_for_selector('[data-action="open-add-project"]', timeout=15000)
    assert "terminal" not in page.inner_text("body").lower()
    page.click('[data-action="open-add-project"] >> nth=0')
    page.wait_for_selector('[data-bind="add-roots"]')
    assert "somente leitura" in page.inner_text('[data-bind="add-roots"]')
    page.fill("#new-project-name", NAME)
    page.fill("#new-project-path", WIN)
    page.click('[data-action="submit-add-project"]')
    page.wait_for_selector(f".project-item >> text={NAME}", timeout=15000)
    page.screenshot(path=str(SHOTS / "dkr-01-registrado.png"))
    assert any(p["name"] == NAME for p in _projects())
    assert not errs


def test_02_navegar_selecionar_e_segredo_bloqueado(page_ctx):
    page, _ = page_ctx
    page.click(f".project-item >> text={NAME}")
    page.wait_for_selector(".file-tree-item")
    page.click('.file-tree-item:has-text("src")')
    page.click('.file-tree-item:has-text("a.py")')
    page.wait_for_selector(".file-tree-item.is-selected")
    page.wait_for_selector(".file-viewer-overlay")
    page.keyboard.press("Escape")
    page.wait_for_selector(".file-viewer-overlay", state="detached")
    page.click('.file-tree-item:has-text("segredo.env")')
    page.wait_for_timeout(1000)
    assert "VALOR_FALSO" not in page.inner_text("body")
    pid = next(p["id"] for p in _projects() if p["name"] == NAME)
    s, r = _j("GET", f"/api/projects/{pid}/file?path=segredo.env")
    assert s == 403 and r["error"]["code"] == "secret_file"
    page.keyboard.press("Escape")


def test_03_indexar_consultar_exportar_sem_segredos(page_ctx, live):
    pid = next(p["id"] for p in _projects() if p["name"] == NAME)
    _job("initialize", {"project_id": pid, "dry_run": False})
    st = _j("GET", f"/api/workspace/io/status?project_id={pid}")[1]
    assert st["index"]["indexed"] and st["index"]["files"] == 3 and st["availability"]["read_only"]
    s, r = _j("GET", f"/api/projects/{pid}/files?q=soma&content=1")
    assert any(x["path"] == "src/a.py" for x in r["results"])
    s, r = _j("GET", "/api/memory/search-preview?q=Estrutura%20do%20projeto%20WIO%20UI%20Demo")
    assert any("wio-ui-demo" in x["file"] for x in r["sources"])
    for kind, fmt in [("index", "json"), ("index", "md"), ("index", "csv"), ("memories", "json"), ("report", "json")]:
        j = _job("export", {"project_id": pid, "kind": kind, "format": fmt, "dry_run": False, "scope": "project"})
        s, body = _api("GET", f"/api/workspace/io/jobs/{j['id']}/download")
        assert s == 200 and body, (kind, fmt, s)
        txt = body.decode("utf-8", "ignore")
        assert "nao-e-segredo-real" not in txt and "VALOR_FALSO" not in txt and _token() not in txt
        if kind == "index" and fmt == "json":
            data = json.loads(body)["data"]
            assert sorted(x["path"] for x in data) == ["README.md", "nota.md", "src/a.py"]
            for x in data:
                assert x["sha256"] == hashlib.sha256((DEMO / x["path"]).read_bytes()).hexdigest()


def test_04_escopo_negado():
    pid = next(p["id"] for p in _projects() if p["name"] == NAME)
    s, r = _j("POST", "/api/projects", {"name": "fora", "path": "D:\\qualquer"})
    assert s == 403 and r["error"]["code"] == "path_not_mapped"
    s, r = _j("POST", "/api/projects", {"name": "trav", "path": DEMO_ROOT_WIN + "\\..\\Windows"})
    assert s == 403 and r["error"]["code"] == "path_escape"
    for rel in ("../README.md", "..%2F..%2Fetc%2Fpasswd", "%2Fetc%2Fpasswd"):
        s, r = _j("GET", f"/api/projects/{pid}/file?path={rel}")
        assert s == 403 and r["error"]["code"] == "path_escape", rel
    for cmd in ("touch /projects/_wio_ui_demo/x.txt", "rm /projects/_wio_ui_demo/README.md", "ln -s /etc /projects/_wio_ui_demo/lnk"):
        p = subprocess.run(["docker", "exec", CONT, "sh", "-c", cmd], capture_output=True, text=True)
        assert p.returncode != 0 and "Read-only" in p.stderr, cmd
    assert not (DEMO / "x.txt").exists() and not (DEMO / "lnk").exists()


def test_05_remover_cancelar_e_confirmar(page_ctx, live):
    page, errs = page_ctx
    page.goto(BASE + "/#/workspace")
    page.reload()
    page.wait_for_selector(f".project-item >> text={NAME}", timeout=15000)
    page.click(f".project-item >> text={NAME}")
    page.click('[data-action="remove-project"]', timeout=8000)
    page.wait_for_selector('[data-bind="rm-modal"]')
    assert "NÃO são apagados" in page.inner_text('[data-bind="rm-modal"]')
    page.screenshot(path=str(SHOTS / "dkr-02-modal-remover.png"))
    page.click("#rm-cancel")
    page.wait_for_timeout(400)
    assert page.locator('[data-bind="rm-modal"]').count() == 0 and any(p["name"] == NAME for p in _projects())
    page.click('[data-action="remove-project"]', timeout=8000)
    page.wait_for_selector("#rm-confirm")
    page.click("#rm-confirm")
    page.wait_for_function("() => document.body.innerText.includes('removido')", timeout=10000)
    assert not any(p["name"] == NAME for p in _projects())
    assert _tree_hash() == live
    assert not errs
