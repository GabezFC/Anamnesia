"""E2E real do Workspace (servidor uvicorn real + Chromium). Pulado sem ANAMNESIA_E2E=1 ou sem playwright.

    ANAMNESIA_E2E=1 <python com playwright> -m pytest tests/e2e/test_workspace_e2e.py -q

Sobe o app com ANAMNESIA_HOME/MG_LOCAL_TOKEN isolados (nunca toca dados reais), cadastra um projeto temporário
via API e exercita a Central pela UI: sem terminal, status real, inicializar, importar, exportar, histórico,
responsividade (1400x900 e 800x700) sem overflow/sobreposição. Capturas em reports/workspace-e2e/.
"""
from __future__ import annotations

import json
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
SIZES = [(1400, 900), (800, 700)]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server_python() -> str:
    cand = os.environ.get("E2E_SERVER_PYTHON")
    if cand:
        return cand
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv if venv.exists() else sys.executable)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    base = tmp_path_factory.mktemp("wse2e")
    proj = base / "proj"
    (proj / "memorias").mkdir(parents=True)
    (proj / "memorias" / "nota.md").write_text("---\ntitle: Nota E2E\ntags: [e2e]\n---\n\nConteudo da nota.\n", encoding="utf-8")
    (proj / "main.py").write_text("print('oi')\n", encoding="utf-8")
    (proj / ".env").write_text("SECRET=1\n", encoding="utf-8")
    port = _free_port()
    env = {**os.environ, "ANAMNESIA_HOME": str(base / "home"), "MG_LOCAL_TOKEN": TOKEN, "PYTHONUTF8": "1"}
    env.pop("MG_HOST", None)
    log = open(base / "server.log", "w", encoding="utf-8")
    proc = subprocess.Popen([_server_python(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(url + "/", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.fail("servidor não subiu: " + (base / "server.log").read_text(encoding="utf-8")[-800:])
        req = urllib.request.Request(url + "/api/projects", method="POST",
                                     data=json.dumps({"name": "Projeto E2E", "path": str(proj)}).encode(),
                                     headers={"Content-Type": "application/json", "X-MG-Token": TOKEN, "Origin": url, "Referer": url + "/"})
        urllib.request.urlopen(req, timeout=10)
        yield {"url": url, "proj": proj}
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
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


OVERFLOW_JS = """() => {
  const vw = document.documentElement.clientWidth;
  const root = document.querySelector('.workspace-layout');
  const bad = [];
  const scrollers = new Set();
  for (const el of root.querySelectorAll('*')) if (['auto','scroll'].includes(getComputedStyle(el).overflowX)) scrollers.add(el);
  const inScroller = (el) => { for (let p = el.parentElement; p && p !== root; p = p.parentElement) if (scrollers.has(p)) return true; return false; };
  for (const el of root.querySelectorAll('*')) {
    if (inScroller(el) || getComputedStyle(el).position === 'fixed') continue;
    const r = el.getBoundingClientRect();
    if (r.width && el.offsetParent !== null && (r.right > vw + 1 || r.left < -1) && !el.closest('.drawer, .ws-resizer, .u-visually-hidden')) bad.push(el.tagName + '.' + el.className + ' ' + Math.round(r.left) + '..' + Math.round(r.right));
  }
  const cut = [...root.querySelectorAll('.wio-project *, .wio-hint, .wio-tab, .btn, .wio-history li *')]
    .filter((e) => !inScroller(e) && getComputedStyle(e).overflow !== 'hidden' && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline')
    .map((e) => e.tagName + '.' + e.className + ' ' + e.scrollWidth + '>' + e.clientWidth);
  return { vw, bad, cut, docScroll: [document.scrollingElement.scrollWidth, document.scrollingElement.clientWidth] };
}"""


def _open(browser, server, w, h):
    page = browser.new_page(viewport={"width": w, "height": h})
    page.goto(server["url"] + "/#/workspace")
    page.wait_for_selector(".wio-tab", timeout=15000)
    return page


@pytest.mark.parametrize("w,h", SIZES)
def test_no_terminal_no_black_void_and_no_overflow(browser, server, w, h):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page = _open(browser, server, w, h)
    page.wait_for_selector(".wio-project .wio-pill", timeout=10000)
    text = page.inner_text(".workspace-layout").lower()
    assert "abra um terminal" not in text and "terminal" not in text, "texto de terminal embutido ainda visível"
    assert page.locator(".terminal-window-card, .terminal-panes-wrapper, .terminal-mount-container, .xterm").count() == 0
    # o painel principal é a Central e começa logo no topo (sem reserva de espaço vazio acima)
    top = page.evaluate("document.querySelector('.workspace-center-col').getBoundingClientRect().top")
    first = page.evaluate("document.querySelector('.workspace-center-col .wio-header').getBoundingClientRect().top")
    assert first - top < 40
    res = page.evaluate(OVERFLOW_JS)
    page.screenshot(path=str(SHOTS / f"central-{w}x{h}.png"))
    assert not res["bad"], res["bad"][:8]
    assert not res["cut"], res["cut"][:8]
    assert res["docScroll"][0] <= res["docScroll"][1] + 1, res["docScroll"]
    page.close()


def test_central_flow_status_init_import_export_history(browser, server):
    page = _open(browser, server, 1400, 900)
    page.wait_for_selector(".wio-project .wio-pill")
    card = page.inner_text(".wio-project")
    assert "Projeto E2E" in card and "não indexado" in card          # status real, sem índice ainda
    # Inicializar: prévia (não grava) -> aplicar
    page.click('[data-action="wio-dry"][data-kind="init"]')
    page.wait_for_selector(".wio-job >> text=Prévia concluída")
    assert "não indexado" in page.inner_text(".wio-project")           # prévia não grava
    page.click('[data-action="wio-run"][data-kind="init"]')
    page.wait_for_selector(".wio-project >> text=itens indexados", timeout=20000)
    assert "Atualizar índice" in page.inner_text(".wio-actions")        # ações mudam com o estado real
    # Importar da pasta do projeto
    page.click('[data-tab="import"]')
    page.check('[data-wio-src][value="path"]')
    page.fill("#wio-import-path", "memorias")
    page.click('[data-action="wio-dry"][data-kind="import"]')
    page.wait_for_selector(".wio-job >> text=Prévia concluída")
    page.click('[data-action="wio-run"][data-kind="import"]')
    page.wait_for_selector(".wio-job >> text=Operação aplicada", timeout=20000)
    # caminho inexistente -> erro claro
    page.fill("#wio-import-path", "nao/existe")
    page.click('[data-action="wio-dry"][data-kind="import"]')
    page.wait_for_selector(".wio-alert >> text=não encontrado")
    # Exportar memórias e baixar
    page.click('[data-tab="export"]')
    page.click('[data-action="wio-run"][data-kind="export"]')
    page.wait_for_selector('[data-action="wio-download"]', timeout=20000)
    with page.expect_download() as dl:
        page.click('[data-action="wio-download"]')
    assert dl.value.suggested_filename.endswith(".json")
    # Histórico persistente (só operações aplicadas)
    hist = page.inner_text(".wio-hist")
    assert "Inicializar" in hist and "Importar" in hist and "Exportar" in hist
    page.reload()
    page.wait_for_selector(".wio-hist li")
    assert page.locator(".wio-hist li").count() >= 3
    page.close()
