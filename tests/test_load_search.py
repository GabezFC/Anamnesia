"""ANA-059: the load/concurrency harness itself (tiny scale; the 10k-note run is a script, not a test)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_p = Path(__file__).resolve().parents[1] / "scripts" / "load_search.py"
_spec = importlib.util.spec_from_file_location("load_search", _p)
assert _spec and _spec.loader
ls = importlib.util.module_from_spec(_spec)
sys.modules["load_search"] = ls
_spec.loader.exec_module(ls)


@pytest.fixture(scope="module")
def report():
    return ls.run(notes=60, clients=[1, 4], requests=12, persist=True)


def test_report_shape_and_no_errors(report):
    assert report["notes"] == 60 and [lv["clients"] for lv in report["levels"]] == [1, 4]
    for lv in report["levels"]:
        assert lv["errors"] == 0 and lv["ok"] == 12
        assert 0 < lv["p50_ms"] <= lv["p95_ms"] <= lv["max_ms"]
        assert lv["throughput_rps"] > 0
        assert lv["lock_wait"]["acquires"] >= 12            # persisted: the write lock was exercised
        assert "rss_mb_peak" in lv


def test_gate_flags_regression_and_errors(report):
    assert ls.gate(report, report, 1.5) == []
    slow = {"levels": [{"clients": lv["clients"], "p95_ms": lv["p95_ms"] / 10} for lv in report["levels"]]}
    bad = ls.gate(report, slow, 1.5)
    assert len(bad) == 2 and "p95" in bad[0]
    broken = {**report, "levels": [{**report["levels"][0], "errors": 2}]}
    assert any("erros" in b for b in ls.gate(broken, report, 1.5))


def test_vault_builder_is_deterministic(tmp_path):
    a = ls.build_vault(tmp_path / "a", 5)
    b = ls.build_vault(tmp_path / "b", 5)
    assert a == b and len(list((tmp_path / "a").rglob("*.md"))) == 5
    assert (tmp_path / "a" / "area00" / "nota-00000.md").read_text() == (
        tmp_path / "b" / "area00" / "nota-00000.md").read_text()


def test_percentile_helper():
    assert ls.pct([1, 2, 3, 4, 100], 50) == 3 and ls.pct([], 95) != ls.pct([], 95)   # NaN for empty
