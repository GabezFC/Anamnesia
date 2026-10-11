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
    assert "/static/js/app.js" in refs and "/static/vendor/xterm/xterm.css" in refs
    for r in refs:
        assert (FRONT / r.removeprefix("/static/")).is_file(), r
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+\s*=", html)
    assert not re.search(r'(?:src|href)="\s*(?:https?:)?//', html)


def test_backend_serves_index_and_static_assets():
    c = _client()
    assert c.get("/").status_code == 200
    for p in ("/static/css/tokens.css", "/static/js/app.js", "/static/js/live.js", "/static/vendor/xterm/xterm.js"):
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
    allowed = {"terminal-view.js", "terminals.js", "mock-data.js", "format.js"}  # ANSI palettes / legacy helper, not styling
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


def test_terminal_is_presented_as_local_to_the_app():
    for name in ("components/terminal-view.js", "pages/workspace.js"):
        s = read(FRONT / "js" / name)
        visible = re.sub(r"//.*|/\*.*?\*/", "", s, flags=re.S)
        assert not re.search(r"""['"`>][^'"`<]*\b(WebSocket|localhost|127\.0\.0\.1|porta \d+)\b""", visible, flags=re.I), name
    live = read(FRONT / "js" / "live.js")
    assert "[data-terminal-mount]" in live and "SessionTerminal" in live
    assert "/api/sessions" in read(FRONT / "js" / "anamnesia-api.js")


def test_backend_values_are_escaped_before_reaching_innerhtml():
    live = read(FRONT / "js" / "live.js")
    assert "const esc = " in live
    for field in ("p.name", "p.path", "c.name", "c.run_id"):
        assert f"esc({field}" in live, field
    app = read(FRONT / "js" / "app.js")
    for expr in ("esc(routeObj.title)", "esc(activeModal.snippet)", "esc(message)"):
        assert expr in app, expr


def test_secret_input_is_password_cleared_and_never_persisted():
    c = read(FRONT / "js" / "pages" / "connections.js")
    assert 'type="password"' in c and 'autocomplete="new-password"' in c
    assert "input.value = ''" in c  # cleared right after the request is built
    for f in JS:
        s = read(f)
        assert not re.search(r"(?:local|session)Storage\.setItem\([^)]*(?:key|secret|token|password)", s, flags=re.I), f.name


def test_unavailable_never_becomes_zero_in_cost_kpis():
    costs = read(FRONT / "js" / "pages" / "costs.js")
    assert "indisponível" in costs and "ORIGIN_PT" in costs
    live = read(FRONT / "js" / "live.js")
    assert "'unavailable'" in live


def test_theme_is_light_by_default_and_toggle_exists():
    assert 'data-theme="light"' in read(FRONT / "index.html")
    tokens = read(FRONT / "css" / "tokens.css")
    assert '[data-theme="dark"]' in tokens
    assert "toggle-theme" in read(FRONT / "js" / "app.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_module_graph_resolves():
    r = subprocess.run(["node", str(ROOT / "scripts" / "check_frontend_imports.mjs")],
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr

# ---------------------------------------------------------------- UX parte 1 (i18n, tema, skeleton, lazy, virtual)
def _node(code: str) -> str:
    r = subprocess.run(["node", "--input-type=module", "-e", code], cwd=str(FRONT / "js"),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_new_shared_components_exist_and_have_documented_api():
    comp = FRONT / "js" / "components"
    assert "export function skeleton(" in read(comp / "skeleton.js")
    assert "export function spinner(" in read(comp / "skeleton.js")
    assert "export function emptyState(" in read(comp / "empty-state.js")
    assert "<svg" in read(comp / "empty-state.js")
    assert "export function createVirtualTable(" in read(comp / "virtual-table.js")


def test_language_switch_persists_and_emits_event():
    app = read(FRONT / "js" / "app.js")
    assert 'data-action="set-lang"' in app and "case 'set-lang'" in app
    i18n = read(FRONT / "js" / "i18n.js")
    assert "anamnesia_lang" in i18n and "anamnesia:lang" in i18n


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_en_dictionary_is_complete_and_switch_updates_live_object():
    out = _node("""
globalThis.localStorage = { _d: {}, getItem(k){return this._d[k] ?? null}, setItem(k,v){this._d[k]=String(v)} };
globalThis.window = { dispatchEvent(e){ globalThis.__ev = e.detail.lang; } };
globalThis.CustomEvent = class { constructor(n, o){ this.type = n; this.detail = o.detail; } };
globalThis.document = { documentElement: { setAttribute(){} } };
const m = await import('./i18n.js');
const before = m.I18N.nav.costs;
m.setLang('en');
console.log(JSON.stringify({ miss: m.missingKeys('en'), before, after: m.I18N.nav.costs, ev: globalThis.__ev, stored: localStorage.getItem('anamnesia_lang') }));
m.setLang('pt');
""")
    import json
    d = json.loads(out)
    assert d["miss"] == [], d["miss"]
    assert d["before"] != d["after"] and d["ev"] == "en" and d["stored"] == "en"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_virtual_table_window_math_renders_only_visible_rows():
    out = _node("""
const { computeRange } = await import('./components/virtual-table.js');
console.log(JSON.stringify([computeRange(0, 400, 40, 10000, 6), computeRange(40000, 400, 40, 10000, 6), computeRange(0, 400, 40, 0, 6)]));
""")
    import json
    a, b, c = json.loads(out)
    assert a == {"start": 0, "end": 16}
    assert b == {"start": 994, "end": 1016}
    assert c == {"start": 0, "end": 0}


def test_terminal_theme_reads_css_tokens_and_reacts_to_theme_switch():
    tv = read(FRONT / "js" / "components" / "terminal-view.js")
    assert "export function readTerminalTheme" in tv and "--term-bg" in tv and "getComputedStyle" in tv
    t = read(FRONT / "js" / "terminals.js")
    assert "readTerminalTheme()" in t and "attributeFilter: ['data-theme']" in t
    assert "term.options.theme" in t


def test_lab_tabs_are_lazy_dynamic_imports():
    idx = read(FRONT / "js" / "pages" / "compare" / "index.js")
    assert not re.search(r"^import \* as \w+ from '\./\w[\w-]*\.js'", idx, flags=re.M)
    assert len(re.findall(r"import\('\./[\w-]+\.js'\)", idx)) == 8
    assert "tabCache" in idx

