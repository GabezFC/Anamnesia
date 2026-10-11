"""Static / node guards: workspace layout persistence, session launcher, Memory page, agent-context panel."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / "frontend"
NODE = shutil.which("node")


def read(rel: str) -> str:
    return (FRONT / rel).read_text(encoding="utf-8")


def test_memory_route_menu_and_css_registered():
    app = read("js/app.js")
    assert "import * as memoryPage from './pages/memory.js'" in app
    assert "'#/memory'" in app and 'href="#/memory"' in app
    assert "/static/css/pages/memory.css" in read("index.html")
    assert (FRONT / "css/pages/memory.css").is_file()


def test_api_block_and_endpoints():
    api = read("js/anamnesia-api.js")
    assert "// ---- workspace/memory ----" in api
    tail = api.split("// ---- workspace/memory ----")[1]
    for frag in ("/api/settings", "/api/memory/last-search", "/api/memory/search-preview", "subagent_role",
                 "/api/benchmark/report."):
        assert frag in tail, frag


def test_layout_persistence_uses_settings_with_debounce_and_only_live_sessions():
    ws = read("js/pages/workspace.js")
    assert "terminal_layout" in ws and "putSettings" in ws and "getSettings" in ws
    assert re.search(r"setTimeout\([^;]*putSettings", ws, re.S)  # debounce
    assert "isLiveSession" in ws and "alive.has" in ws  # restore only sessions still active
    for key in ("order", "focus", "split", "widths"):
        assert key in ws


def test_launcher_options_and_session_chips():
    ws, live = read("js/pages/workspace.js"), read("js/live.js")
    assert 'data-launch-opt="worktree"' in ws and 'data-launch-opt="role"' in ws and 'data-launch-opt="mcp"' in ws
    assert "ws-chip" in ws and "sess.branch" in ws and "sess.role" in ws and "sess.mcp" in ws
    assert "createSessionOpts" in live and "branch: s.branch" in live


def test_context_panel_is_real_not_mock():
    ws = read("js/pages/workspace.js")
    assert "mockRecentContext" not in ws
    assert "lastSearch()" in ws and 'data-action="refresh-context"' in ws and "loadContext(root)" in ws


def test_lab_export_links():
    c = read("js/pages/compare/index.js")
    assert "/api/benchmark/report.md" in c and "/api/benchmark/report.json" in c


def _i18n_keys(lang: str) -> dict:
    src = read("js/i18n-workspace.js")
    assert NODE
    out = subprocess.run(
        [NODE, "--input-type=module", "-e",
         f"import {{ WS_I18N }} from 'file:///{(FRONT / 'js/i18n-workspace.js').as_posix()}';"
         f"console.log(JSON.stringify(WS_I18N['{lang}']))"],
        capture_output=True, text=True, check=True)
    assert src
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_i18n_pt_en_have_same_keys():
    def flat(d, p=""):
        r = set()
        for k, v in d.items():
            r |= flat(v, f"{p}{k}.") if isinstance(v, dict) else {f"{p}{k}"}
        return r
    pt, en = _i18n_keys("pt"), _i18n_keys("en")
    assert flat(pt) == flat(en)
    assert {"memory.title", "nav.memory", "lab.exportMd"} <= flat(pt)


@pytest.mark.skipif(NODE is None, reason="node not installed")
@pytest.mark.parametrize("rel", ["js/pages/workspace.js", "js/pages/memory.js", "js/live.js", "js/app.js",
                                 "js/i18n.js", "js/i18n-workspace.js", "js/anamnesia-api.js",
                                 "js/pages/compare/index.js"])
def test_node_check(rel):
    r = subprocess.run([NODE, "--check", str(FRONT / rel)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_memory_render_escapes_backend_html():
    code = """
    globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
    globalThis.window = globalThis; globalThis.addEventListener = () => {};
    globalThis.document = { documentElement: { setAttribute() {} }, addEventListener() {} };
    const m = await import('file:///%s');
    const h = m.renderSourcesTable([{file:'<img src=x onerror=1>', section:'"><script>', score:0.5, tokens:12, decision:'<b>keep</b>'}])
      + m.renderTotals({context: 10, candidates: 40, sources_sum: 12});
    console.log(JSON.stringify(h));
    """ % (FRONT / "js/pages/memory.js").as_posix()
    r = subprocess.run([NODE, "--input-type=module", "-e", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    html = json.loads(r.stdout.strip().splitlines()[-1])
    assert "<img" not in html and "<script>" not in html and "<b>" not in html
    assert "&lt;img" in html and "12" in html and "40" in html
