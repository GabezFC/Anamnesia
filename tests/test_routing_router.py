from app.routing import load_registry
from app.routing.escalation import next_model
from app.routing.policy import RoutingPolicy, preset
from app.routing.router import difficulty_features, route

HEAD = "version: 1\nmodels:\n"
PRICE = ("    price:\n      input: 1\n      output: 2\n"
         "      source_url: https://example.test/p\n      checked_at: 2026-10-06\n")


def M(id, tier, provider="anthropic", ctx="null", caps="[code]", effort="false", price=False, local=False):
    return (f"  - id: {id}\n    provider: {provider}\n    model: m\n    tier: {tier}\n"
            f"    context_window: {ctx}\n    capabilities: {caps}\n    effort_supported: {effort}\n"
            f"    local: {str(local).lower()}\n" + (PRICE if price else "    price: null\n"))


def reg(tmp_path, *entries):
    p = tmp_path / "r.yaml"
    p.write_text(HEAD + "".join(entries), encoding="utf-8")
    return load_registry(p)


def four(tmp_path, ctx="1000000"):
    return reg(tmp_path,
               M("t1", 1, ctx=ctx), M("t2", 2, ctx=ctx), M("t3", 3, ctx=ctx, effort="true", price=True),
               M("t4", 4, ctx=ctx, effort="true"))


HARD = ("Compare por que o gateway falhou antes e depois da migração e explique passo a passo "
        "a relação entre PostgresPool, asyncpg-0.31 e config/paths.py, analise trade-off")
EASY = "qual a porta do ollama"


def on(name="balanced"):
    return preset(name, enabled=True)


def test_disabled_by_default(tmp_path):
    d = route(EASY, 0, "memory", "low", four(tmp_path), preset("balanced"))
    assert d.model_id is None and d.reason_codes[-1] == "routing_disabled"


def test_deterministic(tmp_path):
    r = four(tmp_path)
    a = route(HARD, 1000, "general", "medium", r, on())
    b = route(HARD, 1000, "general", "medium", r, on())
    assert a == b and a.registry_version == r.version_hash()
    assert a.policy_version == on().version_hash() and a.router_tokens == 0


def test_difficulty_orders_tiers(tmp_path):
    r = four(tmp_path)
    e = route(EASY, 0, "general", "low", r, on("economic"))
    h = route(HARD, 0, "general", "low", r, on("economic"))
    assert 0 <= e.difficulty < h.difficulty <= 1
    assert e.tier < h.tier


def test_presets(tmp_path):
    r = four(tmp_path)
    eco = route(EASY, 0, "general", "low", r, on("economic"))
    bal = route(EASY, 0, "general", "low", r, on("balanced"))
    assert eco.tier < bal.tier and eco.verify == "LIGHT"


def test_max_preset(tmp_path):
    r = four(tmp_path)
    d = route(EASY, 0, "general", "low", r, on("max"))
    assert d.tier == 4 and d.model_id == "t4" and d.verify == "FULL" and d.fallback_chain == []


def test_high_risk_bumps_and_full_verify(tmp_path):
    r = four(tmp_path)
    lo = route(EASY, 0, "general", "low", r, RoutingPolicy(enabled=True))
    hi = route(EASY, 0, "general", "high", r, RoutingPolicy(enabled=True))
    assert hi.tier > lo.tier and hi.verify == "FULL" and lo.verify == "NONE"


def test_unknown_risk_does_not_raise(tmp_path):
    d = route(EASY, 0, "general", "wat", four(tmp_path), on())
    assert "unknown_risk_defaulted" in d.reason_codes and d.model_id


def test_no_eligible_model(tmp_path):
    empty = reg(tmp_path, M("t1", 1))
    d = route(EASY, 0, "general", "low", empty, on(), available_providers={"openai"})
    assert d.model_id is None and "no_eligible_model" in d.reason_codes
    from app.routing import Registry
    for r in (Registry(), None):
        d = route(EASY, 0, "general", "low", r, on())
        assert d.model_id is None and "no_eligible_model" in d.reason_codes
    d = route(EASY, 0, "vision", "low", four(tmp_path), on())
    assert d.model_id is None and "no_eligible_model" in d.reason_codes


def test_effort_handling(tmp_path):
    r = four(tmp_path)
    d4 = route(HARD, 0, "general", "high", r, on("max"))
    assert d4.model_id == "t4" and d4.effort in ("low", "medium", "high")
    d1 = route(EASY, 0, "general", "low", r, on("economic"))
    assert d1.tier == 1 and d1.effort is None


def test_fallback_chain_length_and_order(tmp_path):
    r = four(tmp_path)
    d = route(EASY, 0, "general", "low", r, on("economic"))
    assert d.tier == 1 and d.fallback_chain == ["t2", "t3"]
    p = on("economic"); p.max_escalations = 1
    assert route(EASY, 0, "general", "low", r, p).fallback_chain == ["t2"]
    p.max_escalations = 0
    assert route(EASY, 0, "general", "low", r, p).fallback_chain == []


def test_window_null_never_fits(tmp_path):
    r = reg(tmp_path, M("t1", 1, ctx="null"), M("t2", 2, ctx="null"), M("t3", 3, ctx="200000"))
    d = route(EASY, 5000, "general", "low", r, on("economic"))
    assert d.model_id == "t3" and "context_window_escalation" in d.reason_codes
    # without a context requirement a null-window model is fine
    assert route(EASY, 0, "general", "low", r, on("economic")).model_id == "t1"


def test_context_too_large_for_all(tmp_path):
    r = four(tmp_path, ctx="1000")
    d = route(EASY, 5000, "general", "low", r, on())
    assert d.model_id is None and "context_window_unfit" in d.reason_codes
    r2 = four(tmp_path, ctx="null")
    assert route(EASY, 10, "general", "low", r2, on()).model_id is None


def test_no_cost_estimate_when_price_unavailable(tmp_path):
    r = four(tmp_path)
    d = route(EASY, 0, "general", "low", r, on("economic"))
    assert d.expected_cost_status == "unavailable"
    assert not any(k for k in vars(d) if "cost_usd" in k or "estimate" in k)
    top = route(EASY, 0, "general", "low", reg(tmp_path, M("a", 1, price=True)), on("economic"))
    assert top.expected_cost_status == "verified"
    loc = route(EASY, 0, "general", "low", reg(tmp_path, M("l", 1, provider="ollama", local=True)), on())
    assert loc.expected_cost_status == "local_zero"


def test_unknown_price_sorts_last(tmp_path):
    r = reg(tmp_path, M("nop", 1), M("priced", 1, price=True))
    assert route(EASY, 0, "general", "low", r, on("economic")).model_id == "priced"


def test_multi_hop_cues_pt_and_en():
    p = RoutingPolicy()
    base = difficulty_features("status do gateway", 0, p)["multi_hop"]
    assert base == 0
    assert difficulty_features("compare o gateway e depois o router", 0, p)["multi_hop"] > 0
    assert difficulty_features("find the config and then compare it with the router", 0, p)["multi_hop"] > 0


def test_features_bounded_and_code_cue():
    f = difficulty_features("fix this traceback in worker.py ```def x```", 99999999, RoutingPolicy())
    assert all(0 <= v <= 1 for v in f.values()) and f["code"] > 0 and f["context"] == 1.0
    assert all(0 <= v <= 1 for v in difficulty_features("", 0, RoutingPolicy()).values())


def test_task_kind_capability_filter(tmp_path):
    r = reg(tmp_path, M("c1", 1, caps="[cheap_bulk]"), M("c2", 2, caps="[code]"))
    d = route(EASY, 0, "code", "low", r, on("economic"))
    assert d.model_id == "c2"


def test_next_model(tmp_path):
    d = route(EASY, 0, "general", "low", four(tmp_path), on("economic"))
    assert next_model(d, 0) is None
    assert next_model(d, 1) == "t2" and next_model(d, 2) == "t3"
    assert next_model(d, 3) is None
    miss = route(EASY, 0, "vision", "low", four(tmp_path), on())
    assert next_model(miss, 1) is None
    p = on("economic"); p.max_escalations = 1
    d1 = route(EASY, 0, "general", "low", four(tmp_path), p)
    assert next_model(d1, 1) == "t2" and next_model(d1, 2) is None


def test_default_registry_does_not_raise():
    d = route(HARD, 2000, "code", "high", load_registry(), on())
    assert d.router_tokens == 0 and d.registry_version
