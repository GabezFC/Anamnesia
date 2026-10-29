"""Overflow/cortes de markdown e conteúdo longo na UI (Playwright, viewport real).

Serve `frontend/` estaticamente (sem backend), injeta casos extremos (código longo, tabela larga,
URL gigante, palavra sem espaços, texto extenso) em cartões da UI e verifica, em 4 resoluções,
que nada estoura a viewport e que blocos largos rolam internamente (scroll horizontal próprio).
Requer `playwright` + chromium (pula se ausente). Capturas: reports/md-overflow/.
"""
from __future__ import annotations

import functools
import http.server
import threading
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend"
SHOTS = ROOT / "reports" / "md-overflow"
WIDTHS = [(1920, 1080), (1366, 768), (768, 1024), (390, 844)]

LONG_URL = "https://example.com/" + "segmento-muito-longo/" * 20 + "?q=" + "x" * 200
LONG_WORD = "A" * 300
CODE = "const veryLongLine = " + " + ".join(f"'valor_{i}'" for i in range(60)) + ";"
HTML = f"""
<div class="memory-page" id="md-test-root">
  <section class="card memory-section" id="md-card-1">
    <h2 class="card-title">Título com url {LONG_URL}</h2>
    <div class="md-content" id="md-body">
      <h1>{LONG_WORD}</h1>
      <p>{LONG_URL}</p>
      <p>{LONG_WORD}</p>
      <p>{'Texto extenso de parágrafo com várias palavras. ' * 80}</p>
      <ul><li>{LONG_URL}</li><li><code>{LONG_WORD}</code> inline</li></ul>
      <blockquote>{LONG_URL}</blockquote>
      <pre><code>{CODE}</code></pre>
      <table><thead><tr>{''.join(f'<th>coluna_{i}_com_titulo_longo</th>' for i in range(14))}</tr></thead>
        <tbody><tr>{''.join(f'<td>{LONG_WORD[:40]}{i}</td>' for i in range(14))}</tr></tbody></table>
      <img alt="x" width="3000" height="40" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='3000' height='40'/%3E">
    </div>
  </section>
  <section class="card memory-section" id="md-card-2">
    <pre class="memory-context-pre">{CODE} {LONG_URL}</pre>
    <div class="table-container"><table class="table"><thead><tr>{''.join(f'<th>c{i}</th>' for i in range(12))}</tr></thead>
      <tbody><tr>{''.join(f'<td>{LONG_URL[:60]}</td>' for i in range(12))}</tr></tbody></table></div>
    <div class="mem-note-sub"><span>{LONG_URL}</span><span class="mem-tag">{LONG_WORD}</span></div>
  </section>
</div>
"""


class _Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.path = "/index.html" if self.path.split("?")[0] == "/" else self.path.replace("/static/", "/", 1)
        super().do_GET()

    def log_message(self, *a):  # silencia
        pass


@pytest.fixture(scope="module")
def base_url():
    handler = functools.partial(_Handler, directory=str(FRONT))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


JS_CHECK = """() => {
  const vw = document.documentElement.clientWidth;
  const root = document.getElementById('md-test-root');
  const bad = [];
  const scrollers = new Set();
  for (const el of root.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (['auto', 'scroll'].includes(cs.overflowX)) scrollers.add(el);
  }
  const insideScroller = (el) => { for (let p = el.parentElement; p && p !== root; p = p.parentElement) if (scrollers.has(p)) return true; return false; };
  for (const el of root.querySelectorAll('*')) {
    if (insideScroller(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > vw + 1 || r.left < -1)) bad.push(el.tagName + '.' + el.className + ' right=' + Math.round(r.right));
  }
  const containers = [document.scrollingElement, document.querySelector('.app-content'), document.querySelector('.main-viewport'), root]
    .filter(Boolean).map((e) => [e.className || e.tagName, e.scrollWidth, e.clientWidth]);
  const cut = [...root.querySelectorAll('h1,h2,p,li,blockquote,code,span')]
    .filter((e) => !insideScroller(e) && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).display !== 'inline')
    .map((e) => e.tagName + ' ' + e.scrollWidth + '>' + e.clientWidth);
  const blocks = [...root.querySelectorAll('pre, table')].map((e) => {
    const holder = e.tagName === 'TABLE' ? (e.closest('.table-container, .md-table-wrap') || e) : e;
    return { tag: e.tagName, scrolls: holder.scrollWidth > holder.clientWidth + 1, ok: ['auto', 'scroll'].includes(getComputedStyle(holder).overflowX) || holder.scrollWidth <= holder.clientWidth + 1 };
  });
  return { vw, bad, containers, cut, blocks };
}"""


@pytest.mark.parametrize("w,h", WIDTHS)
def test_markdown_and_long_content_do_not_overflow(base_url, w, h):
    SHOTS.mkdir(parents=True, exist_ok=True)
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # chromium não instalado
            pytest.skip(f"chromium indisponível: {e}")
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(base_url + "/#/memory")
        page.wait_for_selector(".app-content", timeout=10000)
        page.evaluate(
            "(html) => { const c = document.querySelector('.app-content'); c.innerHTML = html; }", HTML
        )
        page.wait_for_timeout(200)
        res = page.evaluate(JS_CHECK)
        page.screenshot(path=str(SHOTS / f"md-{w}.png"))
        browser.close()
    assert not res["bad"], res["bad"][:8]
    for name, sw, cw in res["containers"]:
        assert sw <= cw + 1, (name, sw, cw)
    assert not res["cut"], res["cut"][:8]
    assert all(b["ok"] for b in res["blocks"]), res["blocks"]
