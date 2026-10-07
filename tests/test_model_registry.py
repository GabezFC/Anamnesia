import pytest

from app.routing import RegistryError, load_registry

HEAD = "version: 1\nmodels:\n"


def M(id, provider="anthropic", tier=1, extra="", model="m"):
    return (f"  - id: {id}\n    provider: {provider}\n    model: {model}\n    tier: {tier}\n" + extra)


def write(tmp_path, body, name="m.yaml"):
    p = tmp_path / name
    p.write_text(HEAD + body, encoding="utf-8")
    return p


PRICE = ("    price:\n      input: {i}\n      output: {o}\n"
         "      source_url: https://example.test/p\n      checked_at: 2026-10-06\n")


def test_default_file_loads_and_no_prices():
    reg = load_registry()
    assert reg.models and len(reg.version_hash()) == 64
    for m in reg.models:
        assert m.price is None and m.verified is False
        assert reg.price_status(m.id) == ("local_zero" if m.local else "unavailable")


def test_valid_load_fields(tmp_path):
    p = write(tmp_path, M("a", extra="    context_window: 1000\n    capabilities: [code, tools]\n"
                          "    effort_supported: true\n" + PRICE.format(i=1, o=2.5)) +
              M("b", "ollama", 2, "    local: true\n    price: null\n"))
    reg = load_registry(p)
    a = reg.get("a")
    assert (a.context_window, a.capabilities, a.effort_supported) == (1000, ("code", "tools"), True)
    assert a.price.output == 2.5 and reg.price_status("a") == "verified"
    assert reg.price_status("b") == "local_zero"
    assert reg.get("b").cost_per_mtok() == {"input": 0.0, "output": 0.0}


def test_cloud_null_price_unavailable(tmp_path):
    reg = load_registry(write(tmp_path, M("a", extra="    price: null\n")))
    assert reg.price_status("a") == "unavailable" and reg.get("a").cost_per_mtok() is None


@pytest.mark.parametrize("body,msg", [
    (M("a") + M("a"), "duplicate model id"),
    (M("a", "foo"), "unknown provider"),
    (M("a", tier="high"), "tier must be an integer"),
    (M("a", tier="1.5"), "tier must be an integer"),
    (M("a", extra=PRICE.format(i=-1, o=1)), "negative"),
    (M("a", extra="    price:\n      input: 1\n      output: 1\n"), "source_url and checked_at"),
    (M("a", extra="    price:\n      input: 1\n      output: 1\n      source_url: http://x\n"),
     "source_url and checked_at"),
    (M("a", extra="    context_window: 0\n"), "context_window"),
    (M("a", "ollama", extra="    local: false\n"), "local"),
])
def test_validation_errors(tmp_path, body, msg):
    with pytest.raises(RegistryError, match=msg):
        load_registry(write(tmp_path, body))


def test_missing_models_and_file(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("version: 1\n")
    with pytest.raises(RegistryError, match="models"):
        load_registry(p)
    with pytest.raises(RegistryError, match="cannot read"):
        load_registry(tmp_path / "nope.yaml")


def fixture_reg(tmp_path):
    return load_registry(write(
        tmp_path,
        M("cheap", tier=2, extra="    capabilities: [code]\n    context_window: 8000\n" + PRICE.format(i=1, o=1)) +
        M("pricey", tier=2,
          extra="    capabilities: [code, reasoning]\n    context_window: 200000\n" + PRICE.format(i=10, o=10)) +
        M("unknown", tier=2, extra="    capabilities: [code]\n") +
        M("local", "ollama", 1, "    local: true\n    capabilities: [code]\n    context_window: 4000\n") +
        M("top", tier=3, extra="    capabilities: [code, reasoning, vision]\n    context_window: 1000000\n")))


def test_order_unknown_price_last(tmp_path):
    ids = [m.id for m in fixture_reg(tmp_path).eligible()]
    assert ids == ["local", "cheap", "pricey", "unknown", "top"]


def test_filters(tmp_path):
    r = fixture_reg(tmp_path)
    assert [m.id for m in r.eligible(min_tier=3)] == ["top"]
    assert [m.id for m in r.eligible(capabilities=["reasoning"])] == ["pricey", "top"]
    assert [m.id for m in r.eligible(capabilities=["reasoning", "vision"])] == ["top"]
    assert [m.id for m in r.eligible(min_context=100000)] == ["pricey", "top"]  # null context excluded
    assert [m.id for m in r.eligible(available_providers=["ollama"])] == ["local"]
    assert r.eligible(available_providers=[]) == []
    got = r.eligible(min_tier=2, capabilities=["code"], min_context=5000, available_providers={"anthropic"})
    assert [m.id for m in got] == ["cheap", "pricey", "top"]  # "unknown" has null context


def test_hash_changes(tmp_path):
    p = write(tmp_path, M("a"))
    h1 = load_registry(p).version_hash()
    assert load_registry(p).version_hash() == h1
    p.write_text(p.read_text() + M("b"), encoding="utf-8")
    assert load_registry(p).version_hash() != h1


def test_five_tiers_not_hardcoded(tmp_path):
    body = "".join(M(f"m{t}", tier=t * 10) for t in (1, 2, 3, 4, 5))
    r = load_registry(write(tmp_path, body))
    assert r.tiers() == [10, 20, 30, 40, 50]
    assert [m.id for m in r.eligible(min_tier=25)] == ["m3", "m4", "m5"]


def test_comments_and_quotes(tmp_path):
    p = write(tmp_path, M("a", model="'x # y'").replace("    tier: 1\n", "    tier: 1  # comment\n"))
    m = load_registry(p).get("a")
    assert m.model == "x # y" and m.tier == 1
