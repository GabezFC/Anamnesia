"""ANA-013 / ANA-014: confidence intervals, paired tests, sample-size."""
from __future__ import annotations

import pytest

from app.benchmark import statistics as S


def test_wilson_known_values():
    ci = S.wilson_ci(8, 10)
    assert ci["rate"] == 0.8 and 0.49 < ci["low"] < 0.50 and 0.94 < ci["high"] < 0.96
    assert S.wilson_ci(0, 10)["low"] == 0.0
    assert S.wilson_ci(10, 10)["high"] == 1.0


def test_wilson_empty_is_none_not_zero():
    ci = S.wilson_ci(0, 0)
    assert ci["rate"] is None and ci["low"] is None


def test_wilson_narrows_with_n():
    assert S.wilson_ci(80, 100)["half_width"] < S.wilson_ci(8, 10)["half_width"]


def test_bootstrap_deterministic_and_contains_mean():
    v = [0, 1, 1, 0, 1, 1, 1, 0, 1, 1]
    a, b = S.bootstrap_ci(v, seed=1), S.bootstrap_ci(v, seed=1)
    assert a == b and a["low"] <= a["mean"] <= a["high"]
    assert S.bootstrap_ci([])["n"] == 0


def test_paired_diff_excludes_zero_only_when_real():
    a = [1.0] * 30
    b = [0.5] * 30
    assert S.paired_diff_ci(a, b)["excludes_zero"] is True
    noisy_a = [1, 0, 1, 0, 1, 0, 1, 0]
    noisy_b = [0, 1, 0, 1, 0, 1, 0, 1]
    assert S.paired_diff_ci(noisy_a, noisy_b)["excludes_zero"] is False
    assert S.paired_diff_ci([None], [1.0])["n"] == 0


def test_mcnemar():
    assert S.mcnemar_exact([1] * 10 + [0] * 0, [0] * 10)["p_value"] < 0.01
    assert S.mcnemar_exact([1, 0, 1, 0], [0, 1, 0, 1])["p_value"] == 1.0
    assert S.mcnemar_exact([1, 1], [1, 1])["p_value"] == 1.0


def test_sample_size_textbook():
    # p1=0.5, +10pp, 80% power, alpha .05 -> ~387 per arm (classic table value)
    assert 380 <= S.required_n_two_proportions(0.5, 0.10) <= 395
    assert S.required_n_two_proportions(0.5, 0.20) < S.required_n_two_proportions(0.5, 0.10)


def test_power_report_flags_insufficient_n():
    r = S.power_report(20)
    assert r["sufficient"] is False and r["achieved_power"] < 0.3
    assert S.power_report(500)["sufficient"] is True


def test_invalid_delta():
    with pytest.raises(ValueError):
        S.required_n_two_proportions(0.5, 0)
