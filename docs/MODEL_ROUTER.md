# Model Router (R2 + R3)

Pure and deterministic: zero model calls, zero network, `router_tokens=0`.
**Disabled by default** (`RoutingPolicy.enabled=False`) and **not wired into `memory_search`**.

**Nothing is measured yet. No savings, accuracy or cost reduction is claimed.** Every weight,
cutoff and cue list in `app/routing/policy.py` is an initial guess, to be tuned by the benchmark (R6).

```python
from app.routing import load_registry
from app.routing.policy import preset, RoutingPolicy
from app.routing.router import route
from app.routing.escalation import next_model

policy = preset("balanced", enabled=True)   # 'economic' | 'balanced' | 'max'
d = route(query, context_tokens, task_kind, risk, load_registry(), policy, {"anthropic", "ollama"})
d.model_id, d.tier, d.effort, d.verify, d.difficulty, d.reason_codes
d.fallback_chain          # higher-tier eligible models, at most policy.max_escalations
d.expected_cost_status    # 'verified' | 'local_zero' | 'unavailable' (registry); no money estimate is ever computed
next_model(d, failed_attempts=1)   # model id or None
```

- `task_kind` -> required capabilities via `policy.task_capabilities` (`code`, `reasoning`, `bulk`, `vision`, `tools`, `memory`, `general`). `risk`: `low|medium|high` (verify NONE/LIGHT/FULL by risk, `policy.verify_by_risk`).
- Difficulty (0..1) = weighted mean of features: length, distinct identifiers, multi-hop cues (PT/EN), context size, code cues, reasoning cues, and the `query_fp.classify()` class (reused heuristic). Weights: `policy.weights`.
- Difficulty -> level via `tier_cutoffs` (+ risk bump, floor), mapped onto the tiers present in the registry (no fixed tier count).
- Context: a model with `context_window: null` never fits a context requirement; if cheaper candidates do not fit, the next one is chosen with reason `context_window_escalation`; none fit -> `no_eligible_model` + `context_window_unfit`.
- `effort` is `None` unless the chosen model has `effort_supported`.
- Misses never raise: `model_id=None` with `no_eligible_model` (or `routing_disabled`).
- `max` preset: always the highest tier, verify FULL, no escalation. Unknown price sorts last (registry).
- Decisions carry `registry_version` (file hash) and `policy_version` (hash of the policy).
