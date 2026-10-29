"""E2E real: registrar projeto Windows via ANAMNESIA_PATH_MAP -> remover (cancelar, confirmar) -> pasta intacta.

    ANAMNESIA_E2E=1 <python com playwright> -m pytest tests/e2e/test_workspace_remove_e2e.py -q
Usa a pasta de demonstração (dados falsos) C:/Users/YourUser/Projetos_AI/_wio_ui_demo; criada aqui se faltar.
"""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("ANAMNESIA_E2E") != "1", reason="set ANAMNESIA_E2E=1 to run browser E2E")
pw = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "reports" / "workspace-e2e"
TOKEN = "e2e-token"
DEMO = Path(os.environ.get("E2E_DEMO_DIR", "C:/Users/YourUser/Projetos_AI/_wio_ui_demo"))
WIN = DEMO.as_posix()


def _tree_hash(p: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p.rglob("*")):
        if f.is_file() and "node_modules" not in f.parts:
            h.update(str(f.relative_to(p)).encode() + f.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    if not DEMO.exists():
        (DEMO / "src").mkdir(parents=True)
        (DEMO / "README.md").write_text("# demo (dados falsos)\n", encoding="utf-8")
        (DEMO / "src" / "main.py").write_text("print('demo')\n", encoding="utf-8")
    base = tmp_path_factory.mktemp("rmE2E")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "ANAMNESIA_HOME": str(base / "home"), "MG_LOCAL_TOKEN": TOKEN, "PYTHONUTF8": "1",
           "ANAMNESIA_PATH_MAP": f"{DEMO.parent.as_posix()}={DEMO.parent.as_posix()}", "ANAMNESIA_PROJECT_GUARD": "warn"}
    env.pop("MG_HOST", None)
    py = os.environ.get("E2E_SERVER_PYTHON") or str(ROOT / ".venv" / "Scripts" / "python.exe")
    log = open(base / "server.log", "w", encoding="utf-8")
    cmd = [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(url + "/", timeout=1); break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("servidor não subiu: " + (base / "server.log").read_text(encoding="utf-8")[-800:])
        yield {"url": url, "base": base, "cmd": cmd, "env": env, "log": log}
    finally:
        proc.terminate()
        try: proc.wait(10)
        except subprocess.TimeoutExpired: proc.kill()
        log.close()


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"chromium indisponível: {e}")
        yield b
        b.close()


def test_register_then_remove_keeps_folder(browser, server):
    SHOTS.mkdir(parents=True, exist_ok=True)
    before = _tree_hash(DEMO)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server["url"] + "/#/workspace")
    page.wait_for_selector('[data-action="open-add-project"]', timeout=15000)
    page.click('[data-action="open-add-project"] >> nth=0')
    page.wait_for_selector('[data-bind="add-roots"]')
    assert DEMO.parent.as_posix().lower() in page.inner_text('[data-bind="add-roots"]').lower()  # raízes visíveis
    # erro específico: fora das raízes
    page.fill("#new-project-name", "Fora"); page.fill("#new-project-path", "Z:/qualquer/coisa")
    page.click('[data-action="submit-add-project"]')
    page.wait_for_selector('[data-bind="add-error"][data-error-code="path_not_mapped"]')
    # registro correto com caminho Windows
    page.fill("#new-project-name", "WIO Demo"); page.fill("#new-project-path", WIN.replace("/", "\\"))
    page.click('[data-action="submit-add-project"]')
    page.wait_for_selector(".project-item >> text=WIO Demo", timeout=15000)
    page.screenshot(path=str(SHOTS / "rm-1-registered.png"))
    # remover -> cancelar não altera
    page.click('[data-action="remove-project"]')
    page.wait_for_selector('[data-bind="rm-modal"]')
    assert "WIO Demo" in page.inner_text('[data-bind="rm-name"]') and "_wio_ui_demo" in page.inner_text('[data-bind="rm-path"]')
    page.screenshot(path=str(SHOTS / "rm-2-modal.png"))
    page.click("#rm-cancel")
    page.wait_for_selector('[data-bind="rm-modal"]', state="detached")
    assert page.locator(".project-item >> text=WIO Demo").count() == 1
    # remover -> confirmar
    page.click('[data-action="remove-project"]')
    page.click("#rm-confirm")
    page.wait_for_selector('[data-bind="rm-modal"]', state="detached", timeout=15000)
    page.wait_for_selector(".project-item >> text=WIO Demo", state="detached", timeout=15000)
    page.screenshot(path=str(SHOTS / "rm-3-removed.png"))
    # remoção duplicada via API: 404 limpo
    pid = None
    req = urllib.request.Request(server["url"] + "/api/projects", headers={"X-MG-Token": TOKEN})
    assert b"WIO Demo" not in urllib.request.urlopen(req).read()
    assert _tree_hash(DEMO) == before and DEMO.is_dir()  # pasta física intacta
    page.reload(); page.wait_for_selector('[data-action="open-add-project"]')
    assert page.locator(".project-item >> text=WIO Demo").count() == 0  # persiste
    assert not [e for e in errors if "fmtTime" in e], errors
    page.close()
