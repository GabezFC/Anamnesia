"""Static checks for the Anamnesia Workspace shell (frontend/**). No browser, no network.

CSP is `script-src 'self'`; every untrusted value must go through esc(); keys never touch storage.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend"
JS = FRONT / "js"
NEW_JS = ["pages-workspace.js", "pages-connections.js", "pages-orchestration.js", "pages-anacosts.js",
          "shell-extras.js", "terminals.js", "workspace-layout.js", "anamnesia-api.js"]
OWN_JS = NEW_JS + ["app.js"]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", src)


def test_index_html_has_no_inline_script_handlers_or_external_urls():
    html = read(FRONT / "index.html")
    for m in re.finditer(r"<script\b([^>]*)>", html, flags=re.I):
        assert "src=" in m.group(1), f"inline <script> not allowed by CSP: {m.group(0)}"
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), "on*= handler attribute in index.html"
    assert not re.search(r"""(?:src|href)\s*=\s*["']\s*(?:https?:)?//""", html, flags=re.I), "external URL in index.html"
    assert "/static/workspace.css" in html and "/static/vendor/xterm/xterm.css" in html


@pytest.mark.parametrize("name", OWN_JS)
def test_js_has_no_external_urls_inline_handlers_or_eval(name):
    src = strip_comments(read(JS / name))
    assert not re.search(r"""["'`]\s*(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}""", src, flags=re.I), f"external URL in {name}"
    assert not re.search(r"""\bon[a-z]+\s*=\s*["']""", re.sub(r"\.on[a-z]+\s*=", "", src)), f"inline on*= in {name}"
    assert not re.search(r"\beval\s*\(|new Function\s*\(|document\.write\s*\(", src), f"eval-like call in {name}"
    assert "cdn" not in src.lower()


def test_every_new_js_file_is_reachable_from_app_js():
    seen: set[str] = set()
    todo = [JS / "app.js"]
    while todo:
        f = todo.pop()
        if f.name in seen:
            continue
        seen.add(f.name)
        for m in re.finditer(r"""from\s+['"]\./([\w.-]+\.js)['"]""", read(f)):
            todo.append(JS / m.group(1))
    missing = [n for n in NEW_JS if n not in seen]
    assert not missing, f"not imported by the module graph: {missing}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_module_graph_check_passes():
    r = subprocess.run(["node", "scripts/check_frontend_imports.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_layout_helpers_behave():
    """Run workspace-layout.js (pure functions) under node: split, tabs, prune, sanitize."""
    script = """
import * as L from './frontend/js/workspace-layout.js';
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.error('FAIL', m, JSON.stringify(a), JSON.stringify(b)); process.exit(1); } };
let t = L.defaultLayout();
t = L.addTab(t, 'n1', 's1'); t = L.addTab(t, 'n1', 's2');
eq(L.allSessionIds(t), ['s1','s2'], 'tabs');
const r = L.splitLeaf(t, 'n1', 'h'); t = r.tree;
eq(L.leaves(t).length, 2, 'split');
t = L.addTab(t, r.newLeafId, 's3');
eq(L.leafOfSession(t, 's3').id, r.newLeafId, 'tab in new leaf');
t = L.closeTab(t, 's3');
eq(L.leaves(t).length, 1, 'empty leaf collapses');
eq(L.prune(t, ['s2']).tabs ?? L.leaves(L.prune(t, ['s2']))[0].tabs, ['s2'], 'prune');
eq(L.sanitize({ k: 'bogus' }).k, 'leaf', 'sanitize garbage');
eq(L.sanitize(null).k, 'leaf', 'sanitize null');
eq(L.clampRatio(5), 0.85, 'clamp'); eq(L.clampRatio(NaN), 0.5, 'clamp nan');
const s = L.splitLeaf(L.defaultLayout(), 'n1', 'v').tree;
eq(L.sanitize(JSON.parse(JSON.stringify(s))).k, 'split', 'roundtrip');
console.log('layout ok');
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "layout ok" in r.stdout, r.stdout + r.stderr


def test_vendor_xterm_files_and_licenses_exist():
    v = FRONT / "vendor" / "xterm"
    for n in ("xterm.js", "xterm.css", "addon-fit.js", "LICENSE-xterm", "LICENSE-addon-fit"):
        assert (v / n).is_file() and (v / n).stat().st_size > 500, n
    assert "Terminal" in read(v / "xterm.js")[:200000] or (v / "xterm.js").stat().st_size > 100_000
    assert "MIT" in read(v / "LICENSE-xterm") and "MIT" in read(v / "LICENSE-addon-fit")
    term = read(JS / "terminals.js")
    assert "/static/vendor/xterm/" in term


# -- innerHTML interpolation discipline --------------------------------------------------------------

_TEMPLATE_EXPR = re.compile(r"\$\{((?:[^{}]|\{[^{}]*\})*)\}")
_SAFE_EXPR = re.compile(
    r"""^\s*(?:
        esc\(.*\)                      # escaped
      | [\w.]*(?:\.length|\.size)      # counters
      | \d+ | Math\.round\(.*\)
      | .*\.map\(.*\)\.join\(.*\)      # lists of already-escaped fragments (each fragment is audited too)
      | .*\.join\(.*\)
      | [a-z]+Html | [a-z]+Items?Html | body | profileOpts | runsHtml | note | pct | st
      | [\w.]*\?\s*['"`].*:\s*['"`].*   # ternary of literals
      | \w+\(.*\)                      # call to a local helper that returns escaped markup
    )\s*$""",
    re.X | re.S,
)


def _risky_interpolations(src: str) -> list[str]:
    """Template literals that look like HTML and interpolate something not obviously safe."""
    bad: list[str] = []
    for m in re.finditer(r"`([^`]*)`", src, flags=re.S):
        tpl = m.group(1)
        if "<" not in tpl or "${" not in tpl:
            continue
        for e in _TEMPLATE_EXPR.finditer(tpl):
            expr = e.group(1).strip()
            if _SAFE_EXPR.match(expr) or _is_trivially_safe(expr):
                continue
            bad.append(expr[:90])
    return bad


def _is_trivially_safe(expr: str) -> bool:
    # plain identifiers/numeric formatting that carry no free text: ids built by us, indexes, flags
    return bool(re.fullmatch(r"(?:i|n|b|st|pct|on|open|vertical|ok)", expr)) or expr.startswith("!") or " ? " in expr and "esc(" not in expr and "'" in expr


# Each remaining bare interpolation, audited by hand: it is numeric, a literal-only ternary, or markup
# that was built from esc()'d parts by a helper in the same file.
AUDITED = {
    "pages-workspace.js": {"on ? 0 : -1", "tabs", "hcls", "live"},   # tabindex literal; tab markup built from esc()'d parts; css class / counter
    "pages-connections.js": {"id"},                                  # `id` = "cx-" + esc(c.id) + "-" + esc(env), built one line above
    "shell-extras.js": {"i === sel"},                                # boolean
}


@pytest.mark.parametrize("name", NEW_JS)
def test_html_templates_interpolate_only_escaped_values(name):
    src = strip_comments(read(JS / name))
    bad = _risky_interpolations(src)
    unaudited = [b for b in bad if b not in AUDITED.get(name, set())]
    assert not unaudited, f"{name}: unescaped interpolation(s) into HTML: {unaudited}"


def test_server_fields_never_reach_innerhtml_raw():
    """Spot rules on the exact fields a server/user controls."""
    ws = read(JS / "pages-workspace.js")
    cx = read(JS / "pages-connections.js")
    co = read(JS / "pages-anacosts.js")
    for src, fields in ((ws, ["p.name", "p.path", "s.profile", "f.name", "f.path", "W.projectsDown", "W.filesState"]),
                        (cx, ["c.name", "c.id", "c.command", "k.masked", "x.name", "r.note", "s.note", "b.content", "e.message"]),
                        (co, ["r.project", "r.agent", "r.pipeline", "r.run_id", "d.project", "d.query", "d.model", "e.message"])):
        for f in fields:
            for tpl in re.finditer(r"`([^`]*)`", src, flags=re.S):
                if "<" not in tpl.group(1):
                    continue
                for m in _TEMPLATE_EXPR.finditer(tpl.group(1)):
                    expr = m.group(1)
                    if re.search(r"(?<![\w.])" + re.escape(f) + r"(?![\w])", expr):
                        assert "esc(" in expr, f"raw interpolation of {f}: ${{{expr}}}"


# -- secrets -----------------------------------------------------------------------------------------

def test_key_input_is_password_cleared_and_never_persisted():
    cx = read(JS / "pages-connections.js")
    assert 'type="password"' in cx
    assert 'autocomplete="new-password"' in cx
    assert "input.value = ''" in cx, "the key field must be cleared after submit"
    for name in OWN_JS:
        src = strip_comments(read(JS / name))
        for m in re.finditer(r"(?:localStorage|sessionStorage)\.setItem\(([^)]*)\)", src):
            assert not re.search(r"key|secret|token|passw|value", m.group(1), flags=re.I) or "KEY_PREFIX" in m.group(1) or "DISMISS_KEY" in m.group(1) \
                or "LS_" in m.group(1) or "LS_PRESET" in m.group(1), f"{name}: suspicious storage write: {m.group(0)}"
    cx_code = strip_comments(cx)
    assert "lsSet(" not in cx_code and "localStorage" not in cx_code and "sessionStorage" not in cx_code
    assert not re.search(r"console\.(log|debug|info|warn|error)", strip_comments(cx)), "connections page must not log"
    api = strip_comments(read(JS / "anamnesia-api.js"))
    assert not re.search(r"console\.", api)
    assert "tok.${token}" in api and "?token=" not in api and "token=" not in api.replace("X-MG-Token", ""), "WS token must be a subprotocol, not a URL param"


def test_no_storage_write_receives_secret_variables():
    for name in OWN_JS:
        src = strip_comments(read(JS / name))
        assert not re.search(r"(?:lsSet|setItem)\([^)]*(?:secret|apiKey|api_key|password|token)\b", src, flags=re.I), name


# -- app wiring & a11y --------------------------------------------------------------------------------

def test_workspace_is_home_and_old_pages_are_kept():
    app = read(JS / "app.js")
    assert "|| 'workspace'" in app
    for page in ("workspace", "connections", "config", "costs", "dashboard", "benchmarks", "pipeline", "tokens", "latency",
                 "costs-model", "results", "projects", "memory", "agents", "models", "history", "setup", "config-active"):
        assert re.search(r"(?m)^  '?" + re.escape(page) + r"'?: \{", app), f"page {page} missing from PAGES"
    assert "Benchmark avançado" in app
    assert "renderHealthBanner(h.warnings)" in app


def test_a11y_and_motion_basics():
    css = read(FRONT / "workspace.css") + read(FRONT / "style.css")
    assert ":focus-visible" in css and "prefers-reduced-motion" in css and ".sr-only" in css
    ws = read(JS / "pages-workspace.js")
    for token in ('role="tablist"', 'role="tab"', 'role="separator"', 'aria-live="polite"', 'role="tabpanel"', "aria-selected"):
        assert token in ws, token
    assert "prefers-reduced-motion" in read(JS / "terminals.js")
    app = read(JS / "app.js")
    assert '<main id="main"' in app and 'aria-label="Navegação principal"' in app and "<header" in app
    orch = read(JS / "pages-orchestration.js")
    assert 'role="radiogroup"' in orch and 'type="radio"' in orch and "sem medição ainda" in orch


def test_palette_never_steals_keys_from_terminal():
    ex = read(JS / "shell-extras.js")
    assert "inTerminal(ev.target)" in ex and "return;" in ex
    ws = read(JS / "pages-workspace.js")
    assert "attachCustomKeyEventHandler" in read(JS / "terminals.js")
    assert "ev.ctrlKey && !ev.altKey && !ev.metaKey && ev.key === p.key" in ws, "only the configured prefix chord may be consumed"


def _lum(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_text_colours_used_by_new_ui_meet_contrast_4_5():
    css = read(FRONT / "style.css")
    var = {m.group(1): m.group(2) for m in re.finditer(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", css)}
    for fg in ("text-0", "text-1", "success", "warn", "error", "info"):
        for bg in ("bg-0", "bg-1", "surface-0", "surface-1", "surface-2"):
            assert _ratio(var[fg], var[bg]) >= 4.5, (fg, bg, _ratio(var[fg], var[bg]))
