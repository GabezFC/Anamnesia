"""Static regression checks for the 4 UI bugs found by the E2E run (title, scroll, banner, Salvar)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parent.parent / "frontend"
JS = FRONT / "js"
node = shutil.which("node")
needs_node = pytest.mark.skipif(not node, reason="node not installed")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _page_ids() -> list[str]:
    src = read(JS / "app.js")
    block = src[src.index("const PAGES = {"):src.index("/** UI state persisted")]
    return re.findall(r"^  '?([\w-]+)'?: \{$", block, re.M)


# ---- (1) document title follows the view -------------------------------------------------
def test_navigate_sets_document_title_via_t():
    src = read(JS / "app.js")
    assert re.search(r"import \{[^}]*\bt\b[^}]*\} from './i18n\.js'", src)
    nav = src[src.index("async function navigate()"):]
    assert "document.title" in nav.split("try {")[0]


def test_every_page_has_title_key_in_both_languages():
    ids = _page_ids()
    assert len(ids) >= 18
    src = read(JS / "i18n.js")
    pt, en = src[:src.index("const EN = {")], src[src.index("const EN = {"):]
    for i in ids + ["app.title.suffix"]:
        key = "app.title.suffix" if i == "app.title.suffix" else f"page.title.{i}"
        assert f"'{key}'" in pt, key
        assert f"'{key}'" in en, key


@needs_node
def test_en_titles_differ_where_translated():
    code = f"import('{(JS / 'i18n.js').as_uri()}').then(m => console.log(JSON.stringify(m.DICT)))"
    r = subprocess.run([node, "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["pt"]["page.title.connections"] == "Conexões"
    assert d["en"]["page.title.connections"] == "Connections"
    assert set(d["pt"]) == set(d["en"])


# ---- (2) opens at the top ---------------------------------------------------------------
def test_scroll_reset_on_route_change_and_manual_restoration():
    src = read(JS / "app.js")
    assert "scrollRestoration = 'manual'" in src
    nav = src[src.index("async function navigate()"):]
    assert "window.scrollTo(0, 0)" in nav
    assert "lastPageId" in nav  # only on route change, not on toggle re-render


# ---- (3) health banner never squashes the terminal --------------------------------------
def test_health_banner_compact_and_terminal_keeps_height():
    css = read(FRONT / "workspace.css")
    banner = re.search(r"\.health-banner \{[^}]*\}", css).group(0)
    assert "flex: 0 0 auto" in banner
    assert re.search(r"body\.page-wide \.health-banner \{[^}]*max-height:\s*\d+px", css)
    ws = re.search(r"\n\.ws \{[^}]*\}", css).group(0)
    assert re.search(r"min-height:\s*4\d\dpx", ws)
    assert "flex: 0 0 auto" in ws


# ---- (4) Salvar / primary buttons stay legible in every state ---------------------------
def _lum(h: str) -> float:
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_primary_button_hover_keeps_accent_fill_and_contrast():
    css = read(FRONT / "style.css")
    hover = re.search(r"button\.primary:hover:not\(:disabled\) \{([^}]*)\}", css)
    assert hover, "generic button:hover would repaint .primary with a dark surface"
    bg = re.search(r"background:\s*(#[0-9A-Fa-f]{6})", hover.group(1)).group(1)
    fg = re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", hover.group(1)).group(1)
    assert _contrast(bg, fg) >= 4.5
    base = re.search(r"\nbutton\.primary \{([^}]*)\}", css).group(1)
    assert _contrast("#4F9CF9", re.search(r"(?<![-\w])color:\s*(#[0-9A-Fa-f]{6})", base).group(1)) >= 4.5
    assert re.search(r"button\.primary:disabled \{[^}]*color:", css)
