"""Experiment harness: stub by default, refuses --real without a usable model."""
from __future__ import annotations

import importlib.util
import pathlib

from app.orchestration.launchers import FakeLauncher
from tests.orch_helpers import project, three

_p = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "orchestration_experiment.py"
_spec = importlib.util.spec_from_file_location("orch_experiment", _p)
exp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(exp)


def test_stub_experiment_table(tmp_path):
    rows = exp.run_experiment("t", 2, lambda: FakeLauncher(input_tokens=1000, output_tokens=300),
                              three(tmp_path), project(tmp_path))
    assert len(rows) == 3 * 2 * 3
    assert {r["cost_label"] for r in rows} == {"measured"}
    txt = exp.render(rows, "STUB")
    assert "economic" in txt and "balanced" in txt and "max" in txt and "STUB" in txt
    eco = sum(r["cost"] for r in rows if r["preset"] == "economic" and r["rep"] == 1)
    mx = sum(r["cost"] for r in rows if r["preset"] == "max" and r["rep"] == 1)
    assert eco < mx


def test_unavailable_price_labelled(tmp_path):
    rows = exp.run_experiment("t", 1, lambda: FakeLauncher(input_tokens=5, output_tokens=5),
                              three(tmp_path, price=False), project(tmp_path))
    assert all(r["cost"] is None and r["cost_label"] == "unavailable" for r in rows)
    assert "unavailable" in exp.render(rows, "STUB")


def test_cheaper_label_rule(tmp_path):
    rows = exp.run_experiment("t", 1, lambda: FakeLauncher(input_tokens=1000, output_tokens=300),
                              three(tmp_path), project(tmp_path))
    assert exp.cheaper_label(rows, {}).startswith("no label")
    assert exp.cheaper_label(rows, {"economic": 3, "balanced": 3}) == "economic: cheaper"
    assert exp.cheaper_label(rows, {"economic": 2, "balanced": 3}).startswith("no label")


def test_real_refused_without_usable_model(monkeypatch, capsys):
    import app.routing.answer as ans
    monkeypatch.setattr(ans, "get_availability", lambda: {})
    assert exp.main(["--real", "--reps", "1"]) == 2
    assert "refusing --real" in capsys.readouterr().err


def test_default_main_is_stub(capsys):
    assert exp.main(["--reps", "1"]) == 0
    out = capsys.readouterr().out
    assert "STUB launcher" in out and "no label (stub run)" in out
