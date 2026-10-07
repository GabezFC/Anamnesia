"""Static checks for the Model Routing section of the Custos page (no browser, no network)."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "frontend" / "js" / "pages-anacosts.js"


def src() -> str:
    return JS.read_text(encoding="utf-8")


def test_section_reads_readonly_routing_endpoint():
    s = src()
    assert "/api/costs/routing/summary" in s and "Model Routing" in s
    assert "O router paga o próprio custo?" in s
    assert "sem dados" in s and "SIM" in s and "NÃO" in s


def test_no_inline_handlers_and_no_unescaped_dynamic_text():
    s = src()
    assert not re.search(r"\son(click|change|submit|load|error)\s*=", s)
    assert "javascript:" not in s
    block = s[s.index("const tierHead"):s.index("async function loadRouting")]
    assert "`" not in block                                       # no template literals: concatenation only
    for m in re.finditer(r"\+\s*([^+;]+?)\s*(?=\+|;|$)", block, flags=re.M):
        e = m.group(1).strip()
        if e.startswith("'") or e.startswith(("esc(", "originChip(", "tiers.", "['easy'", "routing", "strat", "netTxt", "stratTable", "sim", "extra", "(")):
            continue
        assert False, f"unescaped concatenation: {e}"


def test_origin_label_next_to_figures_and_matrix_and_escalation():
    block = src()
    assert block.count("originChip(") >= 6
    assert "cs-rt-matrix" in block and "Taxa de escalonamento" in block


def test_node_can_parse_module():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, "--check", str(JS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
