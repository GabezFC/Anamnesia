"""Static guards for the Anamnésia front-end (design from Google AI Studio + live data layer).

No browser, no network: cheap checks for the rules the product depends on (CSP, no distortion in
charts, benchmark isolated in #/compare/*, terminal shown as a local app feature, secrets handling).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
JS = sorted((FRONT / "js").rglob("*.js"))
CSS = sorted((FRONT / "css").rglob("*.css"))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))


def test_index_references_only_existing_local_assets_under_static():
    html = read(FRONT / "index.html")
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert "/static/js/app.js" in refs
    for r in refs:
        assert (FRONT / r.removeprefix("/static/")).is_file(), r
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+\s*=", html)
    assert not re.search(r'(?:src|href)="\s*(?:https?:)?//', html)


def test_backend_serves_index_and_static_assets():
    c = _client()
    assert c.get("/").status_code == 200
    for p in ("/static/css/tokens.css", "/static/js/app.js", "/static/js/live.js"):
        assert c.get(p).status_code == 200, p


@pytest.mark.parametrize("f", JS, ids=lambda f: f.relative_to(FRONT).as_posix())
def test_js_has_no_eval_inline_handlers_or_external_urls(f):
    s = read(f)
    assert not re.search(r"\beval\s*\(|new Function\s*\(|document\.write\s*\(", s)
    assert not re.search(r"""\son(?:click|change|submit|load|error|input|keydown)\s*=\s*["']""", s)
    assert "javascript:" not in s
    assert not re.search(r"""(?:import|fetch)\s*\(?\s*["']https?://""", s)


def test_charts_never_stretch_and_colours_come_from_tokens():
    for f in JS:
        s = read(f)
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", s, flags=re.S)
        assert 'preserveAspectRatio="none"' not in code, f.name
    allowed = {"mock-data.js", "format.js"}  # cores de dados de demo / helper legado, não estilo
    for f in JS:
        if f.name in allowed:
            continue
        assert not re.search(r"#[0-9A-Fa-f]{6}\b", read(f)), f"hex colour outside tokens.css: {f.name}"


def test_stylesheets_have_no_remote_imports_or_fonts():
    for f in CSS:
        s = read(f)
        assert not re.search(r"@import\s+url\(\s*['\"]?https?:", s), f.name
        assert not re.search(r"url\(\s*['\"]?https?:", s), f.name


def test_benchmark_data_lives_only_in_the_lab():
    """Rule of gold: no benchmark chart/table outside #/compare/*."""
    lab = FRONT / "js" / "pages" / "compare"
    assert lab.is_dir() and (lab / "index.js").is_file()
    for f in JS:
        if lab in f.parents:
            continue
        s = read(f)
        if f.name in {"mock-data.js", "live.js"}:
            continue
        assert "mockBenchmark" not in s, f"benchmark leaked into {f.relative_to(FRONT)}"
    app = read(FRONT / "js" / "app.js")
    assert "#/compare" in app and "Comparar Modelos" in read(FRONT / "js" / "i18n.js") + app
    nav = re.findall(r'href="#/(\w+)" class="nav-item', app)
    assert nav == ["workspace", "connections", "config", "costs", "memory"], nav


def test_terminal_ui_is_gone():
    for rel in ("js/pages/workspace.js", "js/live.js"):
        src = read(FRONT / rel)
        for frag in ("/api/sessions", "SessionTerminal", "xterm", "terminal-view"):
            assert frag not in src, (rel, frag)
    assert not (FRONT / "vendor" / "xterm").exists()
    html = read(FRONT / "index.html")
    assert "xterm" not in html


def test_workspace_center_is_the_io_hub():
    ws = read(FRONT / "js" / "pages" / "workspace.js")
    for frag in ("Central de Importação, Exportação e Inicialização", "/api/workspace/io/", "wio-tab",
                 "wio-dry", "wio-run", "wio-cancel"):
        assert frag in ws, frag

def test_lab_tabs_are_lazy_dynamic_imports():
    idx = read(FRONT / "js" / "pages" / "compare" / "index.js")
    assert not re.search(r"^import \* as \w+ from '\./\w[\w-]*\.js'", idx, flags=re.M)
    assert len(re.findall(r"import\('\./[\w-]+\.js'\)", idx)) == 9
    assert "tabCache" in idx

