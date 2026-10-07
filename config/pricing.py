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
