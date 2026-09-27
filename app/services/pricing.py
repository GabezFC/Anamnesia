"""Cost calculations (§63, §64). Unknown price or unknown tokens => None ('unavailable'), never estimated."""
from __future__ import annotations

from config.pricing import price_for


def cost_usd(input_tokens: int | None, output_tokens: int | None, model: str | None,
             provider: str | None = None) -> float | None:
    p = price_for(model, provider)
    if p is None or input_tokens is None:
        return None
    out = output_tokens or 0
    return round(input_tokens / 1e6 * p["input"] + out / 1e6 * p["output"], 8)


def add_costs(*values: float | None) -> float | None:
    """Sum only if every component is known; one unavailable component makes the total unavailable."""
    if any(v is None for v in values):
        return None
    return round(sum(values), 8)


def break_even(graphify: dict, graphify_jev: dict) -> dict:
    """Compare Graphify vs Graphify+JEV for the same question/consumer (§64, §89, §90).

    Inputs are run metric dicts. Reports observed numbers only; no verdict (§91).
    """
    def g(d, k):
        return d.get(k)

    ctx_b, ctx_c = g(graphify, "context_tokens"), g(graphify_jev, "context_tokens")
    out = {
        "jev_token_overhead": g(graphify_jev, "jev_input_tokens"),
        "jev_cost_overhead": g(graphify_jev, "jev_cost"),
        "jev_latency_overhead_ms": g(graphify_jev, "jev_latency_ms"),
        "context_tokens_saved": None if ctx_b is None or ctx_c is None else ctx_b - ctx_c,
        "context_reduction_percent": None if not ctx_b or ctx_c is None else round(100 * (1 - ctx_c / ctx_b), 2),
    }
    docs_b, docs_c = g(graphify, "documents_sent_to_model"), g(graphify_jev, "documents_sent_to_model")
    out["documents_reduction_percent"] = None if not docs_b or docs_c is None else round(100 * (1 - docs_c / docs_b), 2)
    mc_b, mc_c = g(graphify, "model_cost"), g(graphify_jev, "model_cost")
    out["model_cost_savings"] = None if mc_b is None or mc_c is None else round(mc_b - mc_c, 8)
    tc_b, tc_c = g(graphify, "total_cost"), g(graphify_jev, "total_cost")
    out["net_cost_change"] = None if tc_b is None or tc_c is None else round(tc_c - tc_b, 8)
    lb, lc = g(graphify, "total_latency_ms"), g(graphify_jev, "total_latency_ms")
    out["net_latency_change_ms"] = None if lb is None or lc is None else round(lc - lb, 1)
    if out["net_cost_change"] is not None:
        out["net_cost_direction"] = "net_savings" if out["net_cost_change"] < 0 else "net_increase"
    return out
