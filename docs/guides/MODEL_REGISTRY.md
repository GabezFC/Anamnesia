# Model Registry (R1)

Single source: `config/models.yaml`, loaded by `app/routing/registry.py`.

```python
from app.routing import load_registry
reg = load_registry()                       # or load_registry("other.yaml")
reg.eligible(min_tier=2, capabilities=["code"], min_context=100_000,
             available_providers={"anthropic", "ollama"})   # sorted by tier, then price (unknown last)
reg.price_status("anthropic-sonnet")        # 'verified' | 'local_zero' | 'unavailable'
reg.version_hash()                          # sha256 of the file bytes; log in routing decisions
```

- Tiers are integers taken from the file (no fixed count).
- A `price` needs `input`, `output` (>= 0), `source_url`, `checked_at` (YYYY-MM-DD); otherwise `RegistryError`. Cloud models without price are `unavailable`; local ones cost 0.0 (as `config/pricing.py`).
- `context_window: null` = unknown; it never passes a `min_context` filter.
- Starter catalog: every entry is `verified: false` (ids not confirmed against provider lists), no prices.
- Parser: PyYAML is not in requirements, so a YAML-subset parser is used (maps, lists, `[a, b]`, comments).
- Cursor is not a model provider (agent profile).
