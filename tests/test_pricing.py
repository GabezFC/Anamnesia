import pytest

from app.services.pricing import add_costs, break_even, cost_usd
from config.pricing import price_for


def test_jev_cost():
    assert cost_usd(1_000_000, 0, "jev-1.13.0") == pytest.approx(0.042)
    assert cost_usd(12_345, 999, "jev-1.13.0") == pytest.approx(12_345 / 1e6 * 0.042)


def test_unknown_model_none():
    assert price_for("gpt-unknown") is None
    assert cost_usd(100, 10, "gpt-unknown") is None
    assert cost_usd(100, 10, None) is None


def test_unknown_tokens_none():
    assert cost_usd(None, 10, "jev-1.13.0") is None


def test_local_provider_zero():
    assert price_for("qwen", "ollama") == {"input": 0.0, "output": 0.0}
    assert cost_usd(5000, 500, "qwen", provider="ollama") == 0.0


def test_add_costs():
    assert add_costs(0.1, 0.2) == pytest.approx(0.3)
    assert add_costs(0.1, None) is None
    assert add_costs() == 0


def test_break_even():
    g = {"context_tokens": 1000, "documents_sent_to_model": 10, "model_cost": 0.01,
         "total_cost": 0.01, "total_latency_ms": 100.0}
    gj = {"context_tokens": 400, "documents_sent_to_model": 4, "model_cost": 0.004, "total_cost": 0.005,
          "total_latency_ms": 250.0, "jev_input_tokens": 3000, "jev_cost": 0.001, "jev_latency_ms": 150.0}
    out = break_even(g, gj)
    assert out["context_tokens_saved"] == 600
    assert out["context_reduction_percent"] == 60.0
    assert out["documents_reduction_percent"] == 60.0
    assert out["model_cost_savings"] == pytest.approx(0.006)
    assert out["net_cost_change"] == pytest.approx(-0.005)
    assert out["net_cost_direction"] == "net_savings"
    assert out["net_latency_change_ms"] == 150.0
    assert out["jev_token_overhead"] == 3000

    gj2 = dict(gj, total_cost=0.02)
    assert break_even(g, gj2)["net_cost_direction"] == "net_increase"


def test_break_even_unavailable():
    out = break_even({"context_tokens": 0, "total_cost": None}, {"context_tokens": 10, "total_cost": 0.1})
    assert out["context_reduction_percent"] is None
    assert out["net_cost_change"] is None
    assert "net_cost_direction" not in out
