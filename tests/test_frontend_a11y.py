"""ANAM-027/028 (AUD-001,033..044,049): guardas estáticas e unitárias de acessibilidade do frontend.

Sem rede/browser. A execução real por teclado (Playwright) está na nota anam-027-028-a11y.md no Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "js"
CSS = ROOT / "frontend" / "css"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _contrast():
    spec = importlib.util.spec_from_file_location("check_contrast", ROOT / "scripts" / "check_contrast.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------- ANAM-028 contraste
def test_all_token_pairs_meet_wcag_aa():
    m = _contrast()
    after = m.compute(read(CSS / "tokens.css"))
    bad = {k: round(v, 2) for k, v in after.items() if v < m.MIN_RATIO}
    assert len(after) >= 92
    assert not bad, bad


def test_contrast_script_reproduces_audit_cases():
    m = _contrast()
    assert round(m.ratio({"bg-canvas": "#FFFFFF", "a": "#94A3B8", "b": "#FFFFFF"}, "a", "b"), 2) == 2.56  # AUD-042
    assert round(m.ratio({"bg-canvas": "#FFFFFF", "a": "#FFFFFF", "b": "#60A5FA"}, "a", "b"), 2) == 2.54  # AUD-043


def test_dark_primary_button_text_is_dark_enough():
    m = _contrast()
    dark = m.parse_themes(read(CSS / "tokens.css"))["dark"]
    assert m.ratio(dark, "primary-text", "primary") >= 7


# ----------------------------------------------------------------------------- ANAM-027 paleta
def test_palette_is_combobox_listbox_outside_app():
    pal = read(JS / "components" / "command-palette.js")
    for needle in ('role="combobox"', 'aria-activedescendant', 'role="listbox"', 'role="option"', 'aria-live="polite"',
                   "trapFocus", "palette-root", "ArrowDown", "ArrowUp", "Enter", "Escape", "Home", "End"):
        assert needle in pal, needle
    app = read(JS / "app.js")
    assert "renderCommandPalette" not in app and "isCommandPaletteOpen" not in app
    assert 'data-action="palette-navigate"' not in app


def test_no_ghost_shortcut_hints():
    blob = "".join(read(p) for p in JS.rglob("*.js"))
    assert "<kbd>Ctrl+T</kbd>" not in blob
    assert not re.search(r"<kbd>#[1-4]</kbd>", blob)


def test_single_global_keydown_dispatcher_and_terminal_hook():
    app = read(JS / "app.js")
    assert "installShortcutDispatcher" in app
    assert "handleKeyboardShortcuts" not in app
    cmd = read(JS / "commands.js")
    for needle in ("isComposing", "isContentEditable", "registerCommand"):
        assert needle in cmd, needle


def test_document_title_per_route_and_focus_move():
    app = read(JS / "app.js")
    assert "document.title" in app and "updateDocumentTitle" in app
    assert "focusPageHeading" in app


def test_project_modal_labels_and_focus_trap():
    app = read(JS / "app.js")
    assert 'for="new-project-name"' in app and 'for="new-project-path"' in app
    assert "autofocus" not in app
    assert "trapFocus(" in app and "modalTrigger" in app


# ----------------------------------------------------------------------------- ANAM-028 teclado
def test_config_tabs_follow_apg():
    cfg = read(JS / "pages" / "config.js")
    for needle in ('role="tabpanel"', 'aria-controls', 'aria-labelledby', "tabindex=", "handleTablistKey"):
        assert needle in cfg, needle


def test_workspace_tabs_projects_sessions_are_buttons():
    ws = read(JS / "pages" / "workspace.js")
    assert 'role="tab" class="wio-tab' in ws
    assert 'role="tabpanel"' in ws
    assert '<div class="project-item' not in ws and '<div class="session-mini-item' not in ws
    assert 'button type="button" class="project-item' in ws


def test_chart_kit_has_tabular_alternative_and_keyboard_focus():
    kit = read(JS / "charts" / "chart-kit.js")
    assert kit.count("enhanceChart(") == 4  # line, bar, stacked, donut
    a11y = read(JS / "charts" / "chart-a11y.js")
    assert "<details" in a11y and "<table" in a11y and "tabindex" in a11y and "ArrowRight" in a11y


def test_i18n_parity_for_new_a11y_strings():
    src = read(JS / "i18n-onda7.js")
    pt, en = src.split("  en: {", 1)
    for block in ("palette", "a11y"):
        keys = lambda s: set(re.findall(r"^\s{6}(\w+):", s.split(f"    {block}: {{", 1)[1].split("\n    },", 1)[0], flags=re.M))
        assert keys(pt) == keys(en), block


@pytest.mark.skipif(shutil.which("node") is None, reason="node ausente")
def test_commands_registry_guards_in_node(tmp_path):
    """Executa commands.js no Node: registro, atalho gerado do registro, guardas de IME/campo editável."""
    script = tmp_path / "t.mjs"
    script.write_text(
        f"""
import * as c from 'file:///{(JS / "commands.js").as_posix()}';
let ran = [];
c.registerCommand({{ id: 'a', label: 'Alpha', shortcut: 'Alt+Shift+1', run: () => ran.push('a') }});
c.registerCommand({{ id: 'k', label: 'Pal', shortcut: 'Ctrl+K', run: () => ran.push('k') }});
const ed = {{ closest: (s) => s.includes('xterm') ? null : null, tagName: 'INPUT', type: 'text' }};
const body = {{ closest: () => null, tagName: 'DIV' }};
const ev = (o) => ({{ ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, key: '', code: '', target: body, ...o }});
const out = {{
  labels: c.shortcutLabel('Ctrl+K'),
  list: c.listCommands().map((x) => x.id),
  altBody: c.findCommandForEvent(ev({{ altKey: true, shiftKey: true, code: 'Digit1', key: '!' }}))?.id,
  altInput: c.findCommandForEvent(ev({{ altKey: true, shiftKey: true, code: 'Digit1', key: '!', target: ed }}))?.id ?? null,
  ctrlInput: c.findCommandForEvent(ev({{ ctrlKey: true, key: 'k', target: ed }}))?.id,
  ime: c.findCommandForEvent(ev({{ ctrlKey: true, key: 'k', isComposing: true }})) ?? null,
  xtermApp: c.isAppShortcut(ev({{ ctrlKey: true, key: 'k' }})),
  xtermPlain: c.isAppShortcut(ev({{ key: 'a' }})),
  filter: c.filterCommands(c.listCommands(), 'alp').map((x) => x.id),
  nextTab: [c.parseShortcut('Mod+K').mod],
}};
console.log(JSON.stringify(out));
""",
        encoding="utf-8",
    )
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["labels"] == "Ctrl+K" and o["list"] == ["a", "k"]
    assert o["altBody"] == "a" and o["altInput"] is None
    assert o["ctrlInput"] == "k" and o["ime"] is None
    assert o["xtermApp"] is True and o["xtermPlain"] is False
    assert o["filter"] == ["a"] and o["nextTab"] == [True]


@pytest.mark.skipif(shutil.which("node") is None, reason="node ausente")
def test_tabs_next_index_in_node(tmp_path):
    script = tmp_path / "t.mjs"
    script.write_text(
        f"""
import {{ nextTabIndex as n }} from 'file:///{(JS / "components" / "tabs.js").as_posix()}';
console.log(JSON.stringify([n('ArrowRight', 6, 7), n('ArrowLeft', 0, 7), n('Home', 3, 7), n('End', 3, 7), n('x', 3, 7), n('ArrowRight', 0, 0)]));
""",
        encoding="utf-8",
    )
    r = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == [0, 6, 0, 6, -1, -1]
