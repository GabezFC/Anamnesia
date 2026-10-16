"""ANAM-025 / AUD-053..057: rigor do benchmark (citação não verificada, poder estatístico, kill-switch, gate)."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from app.benchmark import routing_bench as rb
from app.benchmark.preflight import BudgetExceeded
from app.benchmark.statistics import power_report, required_n_two_proportions
from tests.test_bench_scoring import _task

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- AUD-053: citation_checked=False nunca é PASS
def test_unchecked_citation_is_not_a_pass():
    r = rb.verify_task(_task(), "O valor é 42. Fonte: a/n.md", None)
    assert r.passed is False and r.failure_code == "citation_unchecked"
    assert r.details["citation_checked"] is False


def test_checked_citation_still_passes():
    r = rb.verify_task(_task(), "O valor é 42. Fonte: a/n.md", ["a/n.md"])
    assert r.passed and r.details["citation_checked"] is True


# ---- AUD-054: N mínimo por poder estatístico
def test_onda4e_n197_is_underpowered_and_required_n_is_recorded():
    pw = power_report(197)
    assert pw["achieved_power"] == 0.514 and pw["sufficient"] is False
    assert required_n_two_proportions(0.5, 0.10) == 388


def test_power_gate_refuses_underpowered_unless_overridden(capsys):
    m = _load("run_onda4e_openrouter")
    pw, need = m.power_gate(197)
    assert pw is None and need == 388
    assert "REFUSED underpowered" in capsys.readouterr().out
    pw, _ = m.power_gate(197, allow_underpowered=True)
    assert pw["sufficient"] is False and pw["n"] == 197
    pw, _ = m.power_gate(400)
    assert pw is not None and pw["sufficient"] is True


# ---- AUD-056: kill-switch do SpendGuard
class _FakeCredits:
    def __init__(self, usage):
        self.u = usage

    def usage(self):
        return {"total_usage": self.u, "total_credits": 100.0}


class _Inner:
    calls = 0

    def __call__(self, task, entry):
        _Inner.calls += 1
        raise AssertionError("não deveria chamar o modelo depois do stop")


def test_spend_guard_trips_kill_switch_and_blocks_inner_call(monkeypatch):
    m = _load("run_onda4e_openrouter")
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    g = m.SpendGuard(_Inner(), _FakeCredits(m.STOP_USD + 0.01), {"baseline_usage": 0.0})
    with pytest.raises(BudgetExceeded):
        g(None, None)
    assert os.environ["ANAMNESIA_PAID_CALLS"] == "0" and g.stopped
    g._c.u = 0.0                                             # stays tripped even if credits "drop"
    with pytest.raises(BudgetExceeded):
        g(None, None)
    assert _Inner.calls == 0


# ---- AUD-055: quality gate de regressão
def _rep(recall, empty=0):
    return {"pipelines": {"baseline": {"recall_pct": recall, "empty_contexts": empty}}}


def test_regression_gate():
    fc = _load("final_comparison")
    assert fc.regression_gate(_rep(90.0), _rep(90.0)) == []
    assert fc.regression_gate(_rep(88.5), _rep(90.0)) == []                 # dentro do ruído
    assert fc.regression_gate(_rep(95.0), _rep(90.0)) == []                 # melhora
    assert "queda" in fc.regression_gate(_rep(80.0), _rep(90.0))[0]
    assert "vazios" in fc.regression_gate(_rep(90.0, 3), _rep(90.0, 0))[0]
    assert "ausente" in fc.regression_gate({"pipelines": {}}, _rep(90.0))[0]
