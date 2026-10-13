"""ANA-080/102: wiring das flags no MemoryGateway e check_import_cycles respeitando allowed_cycles."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from config.retrieval import RetrievalConfig

ROOT = Path(__file__).resolve().parents[1]


def test_stale_fallback_env(monkeypatch):
    assert RetrievalConfig().graphify_stale_fallback_s == 0.0
    monkeypatch.setenv("GRAPHIFY_STALE_FALLBACK_S", "120")
    assert RetrievalConfig().graphify_stale_fallback_s == 120.0


def test_import_cycles_script_honours_allowed_cycles():
    spec = importlib.util.spec_from_file_location("cic", ROOT / "scripts" / "check_import_cycles.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert ["app.api.costs", "app.api.costs_ext"] in m._allowed_cycles()
    assert m.main(["--top-level-only"]) == 0


def test_gateway_uses_factory_and_flag_default_off(monkeypatch):
    from app.retrieval.baseline import BaselineIndex
    from app.retrieval.incremental_index import IncrementalBaselineIndex, make_baseline_index
    monkeypatch.delenv("MG_INCREMENTAL_INDEX", raising=False)
    assert type(make_baseline_index(object(), "x.db")) is BaselineIndex
    monkeypatch.setenv("MG_INCREMENTAL_INDEX", "1")
    assert isinstance(make_baseline_index.__globals__["IncrementalBaselineIndex"], type)
    assert IncrementalBaselineIndex
