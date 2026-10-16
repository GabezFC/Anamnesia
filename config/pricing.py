"""Prices in USD per 1M tokens. Only verified values; anything else => cost 'unavailable' (§63).

Sources:
- jev-1.13.0: https://docs.typesafe.ai/models (checked 2026-09-24): $0.042/Mtok input, output free.
- Local models (Ollama/vLLM): no provider price -> 0.0 marginal API cost (electricity not modelled).
Add cloud model prices here only after checking the provider's official pricing page.
"""

PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "jev-1.13.0": {"input": 0.042, "output": 0.0},
}

LOCAL_PROVIDERS = {"ollama", "vllm", "local"}


def price_for(model: str | None, provider: str | None = None) -> dict[str, float] | None:
    if provider in LOCAL_PROVIDERS:
        return {"input": 0.0, "output": 0.0}
    if model and model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    return None


# Date each price was last checked against the provider's official page (ISO). Same keys as above.
PRICE_CHECKED: dict[str, str] = {"jev-1.13.0": "2026-09-24"}


def price_status(model: str | None, provider: str | None = None) -> dict:
    """How trustworthy a money figure for (model, provider) is. Never invents a price.

    status: "verified" (listed in PRICES_PER_MTOK), "local_zero" (local provider, no API price)
    or "unavailable" (no verified price -> any money figure must be null).
    """
    if provider in LOCAL_PROVIDERS:
        return {"status": "local_zero", "model": model, "provider": provider, "checked": None}
    if model and model in PRICES_PER_MTOK:
        return {"status": "verified", "model": model, "provider": provider,
                "checked": PRICE_CHECKED.get(model)}
    return {"status": "unavailable", "model": model, "provider": provider, "checked": None}


# ---------------------------------------------------------------- ANAM-003: parametrizable price table
# Beyond input/output a model may declare: cache_read, cache_write (prompt caching), thinking (reasoning
# tokens; defaults to the output price) and embedding (embedding models). Missing keys fall back as
# documented in `_component_price`. The table can be extended/overridden WITHOUT code changes by a JSON
# file pointed to by ANAMNESIA_PRICING_FILE: {"<model>": {"input": .., "output": .., "cache_read": ..}}.
# Only values the operator verified should be put there (same rule as above).
PRICING_FILE_ENV = "ANAMNESIA_PRICING_FILE"
UNKNOWN_IN_ENV, UNKNOWN_OUT_ENV = "ANAMNESIA_PRICE_UNKNOWN_IN", "ANAMNESIA_PRICE_UNKNOWN_OUT"
# Pessimistic USD/Mtok used ONLY to *bound* spend for a paid model whose real price is unknown (the
# budget guard must never wave through an unpriced paid call as free). Never shown as a real cost.
DEFAULT_UNKNOWN_PRICE: dict[str, float] = {"input": 15.0, "output": 75.0}


def _load_overrides() -> dict[str, dict[str, float]]:
    import json
    import os
    path = os.environ.get(PRICING_FILE_ENV, "").strip()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        return {str(m): {str(k): float(v) for k, v in p.items() if isinstance(v, (int, float)) and v >= 0}
                for m, p in raw.items() if isinstance(p, dict)}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}     # a broken file must not break routing; the pessimistic unknown price then applies


def price_table() -> dict[str, dict[str, float]]:
    """Built-in table + optional ANAMNESIA_PRICING_FILE overrides (override wins per model)."""
    out = {m: dict(p) for m, p in PRICES_PER_MTOK.items()}
    out.update(_load_overrides())
    return out


def unknown_price() -> dict[str, float]:
    import os
    p = dict(DEFAULT_UNKNOWN_PRICE)
    for key, env in (("input", UNKNOWN_IN_ENV), ("output", UNKNOWN_OUT_ENV)):
        try:
            v = float(os.environ.get(env, "") or p[key])
            p[key] = v if v >= 0 else p[key]
        except ValueError:
            pass
    return p


def _component_price(p: dict[str, float], name: str) -> float:
    """cache_read -> input; cache_write -> input; thinking -> output; embedding -> input."""
    if name in p:
        return p[name]
    return p.get("output", 0.0) if name == "thinking" else p.get("input", 0.0)


def estimate_cost(model: str | None, provider: str | None, *, tokens_in: int = 0, tokens_out: int = 0,
                  cache_read: int = 0, cache_write: int = 0, thinking: int = 0, embedding: int = 0,
                  price: dict[str, float] | None = None) -> tuple[float, str]:
    """(usd, basis). basis: 'local_zero' | 'verified' | 'unknown_price_upper_bound'.
    `price` (e.g. a registry entry's verified price) wins over the table. Unknown paid model -> pessimistic bound."""
    if provider in LOCAL_PROVIDERS:
        return 0.0, "local_zero"
    p, basis = price, "verified"
    if p is None:
        p = price_table().get(model or "")
    if p is None:
        p, basis = unknown_price(), "unknown_price_upper_bound"
    usd = sum(_component_price(p, k) * n for k, n in (
        ("input", tokens_in), ("output", tokens_out), ("cache_read", cache_read),
        ("cache_write", cache_write), ("thinking", thinking), ("embedding", embedding)) if n) / 1_000_000
    return round(usd, 8), basis
