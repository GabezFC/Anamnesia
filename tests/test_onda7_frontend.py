"""Onda 7 (ANA-200/201/206/209/211/212): garantias estáticas e de lógica do frontend do dashboard."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONT = Path(__file__).resolve().parents[1] / "frontend"
JS = FRONT / "js"
CSS = FRONT / "css"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def node(code: str) -> str:
    r = subprocess.run(["node", "--input-type=module", "-e", code], cwd=str(JS), capture_output=True,
                       text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_ana200_live_never_fabricates_zero_or_default_budget():
    live = read(JS / "live.js")
    body = live[live.index("async function loadCosts"):live.index("/* ------------------------------------------------------------------ boot */")]
    assert "?? 0" not in body, "KPI de custo/tokens ausente deve ser null, não 0"
    assert "mk(b.day, 2)" not in body and "mk(b.month, 50)" not in body, "teto de orçamento inventado"
    assert "x?.spent_usd ?? null" in body and "x?.ceiling_usd ?? null" in body


def test_ana201_shell_does_not_show_mock_when_api_down():
    app = read(JS / "app.js")
    assert "isDemo('workspace')" in app and "isDemo('costs')" in app
    assert "mockCostSummary.total_usd.value" in app and "? null :" in app      # só lido quando a API respondeu
    assert "mockBenchmark" not in app


def test_ana203_history_has_no_mock_benchmark():
    for f in (JS / "pages" / "compare").glob("*.js"):
        s = read(f)
        assert "mockBenchmark" not in s and "history_runs" not in s, f.name
    assert "/benchmark/runs" in read(JS / "lab-data.js")


def test_ana211_breakpoints_in_every_page_stylesheet():
    for name in ("workspace", "compare", "memory", "connections", "onda7"):
        css = read(CSS / "pages" / f"{name}.css")
        assert "@media (max-width: 900px)" in css, name
    for name in ("workspace", "compare", "memory", "connections"):
        assert "@media (max-width: 640px)" in read(CSS / "pages" / f"{name}.css"), name


def test_ana212_no_direct_tolocale_outside_format():
    bad = [f.relative_to(JS).as_posix() for f in JS.rglob("*.js")
           if f.name not in ("format.js", "mock-data.js") and "vendor" not in f.parts
           and re.search(r"\.toLocale(?:String|DateString|TimeString)?\(", read(f))]
    assert bad == [], f"use format.js (fmtNumber/fmtDate): {bad}"


@needs_node
def test_ana212_onda7_dictionary_has_pt_en_parity():
    out = node("""
const m = await import('./i18n-onda7.js');
const flat = (o, p = '') => Object.entries(o).flatMap(([k, v]) => v && typeof v === 'object' && !Array.isArray(v) ? flat(v, p + k + '.') : [p + k]);
console.log(JSON.stringify({ pt: flat(m.O7_I18N.pt), en: flat(m.O7_I18N.en) }));
""")
    d = json.loads(out)
    assert d["pt"], "dicionário PT vazio"
    assert sorted(d["pt"]) == sorted(d["en"]), sorted(set(d["pt"]) ^ set(d["en"]))


def test_ana206_a11y_basics():
    assert "setAttribute('lang'" in read(JS / "i18n.js")
    for f in ("compare/index.js", "compare/history.js", "provider-health.js", "memory-extras.js"):
        assert "aria-" in read(JS / "pages" / f), f
    assert 'class="skip-link"' in read(JS / "app.js")


@needs_node
def test_ana209_waterfall_spans_are_sequential_and_flag_reconstruction():
    out = node("""
globalThis.localStorage = { getItem(){return null}, setItem(){} };
const { runSpans } = await import('./lab-data.js');
const ok = runSpans({ metrics: { total_latency_ms: 100, retrieval_ms: 40, jev_ms: 58 } });
const none = runSpans({ metrics: {} });
console.log(JSON.stringify({ ok, none }));
""")
    d = json.loads(out)
    assert d["none"]["spans"] == [] and d["none"]["total"] is None and d["none"]["withinTolerance"] is None
    sp = d["ok"]["spans"]
    assert d["ok"]["reconstructed"] is True
    assert all(a["end"] == b["start"] for a, b in zip(sp, sp[1:]))      # sem lacunas inventadas
    assert d["ok"]["sum"] == sum(s["ms"] for s in sp)
    assert d["ok"]["unattributed"] == d["ok"]["total"] - d["ok"]["sum"]
