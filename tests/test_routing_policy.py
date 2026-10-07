import pytest

from app.routing.policy import PRESET_NAMES, RoutingPolicy, preset


def test_disabled_by_default():
    assert RoutingPolicy().enabled is False
    for n in PRESET_NAMES:
        assert preset(n).enabled is False
        assert preset(n, enabled=True).enabled is True


def test_presets_differ_and_hash_stable():
    hashes = {preset(n).version_hash() for n in PRESET_NAMES}
    assert len(hashes) == 3
    assert preset("balanced").version_hash() == preset("balanced").version_hash()
    assert RoutingPolicy().version_hash() != RoutingPolicy(max_escalations=3).version_hash()


def test_max_preset_shape():
    p = preset("max")
    assert p.always_top_tier and set(p.verify_by_risk.values()) == {"FULL"}


def test_economic_and_balanced_verify():
    assert set(preset("economic").verify_by_risk.values()) == {"LIGHT"}
    assert preset("balanced").verify_by_risk["high"] == "FULL"
    assert preset("economic").max_escalations == 2


def test_defaults():
    p = RoutingPolicy()
    assert p.max_escalations == 2
    assert p.verify_by_risk == {"low": "NONE", "medium": "LIGHT", "high": "FULL"}


def test_validation():
    with pytest.raises(ValueError):
        preset("nope")
    with pytest.raises(ValueError):
        RoutingPolicy(verify_by_risk={"low": "HUGE"})
    with pytest.raises(ValueError):
        RoutingPolicy(tier_cutoffs=(0.8, 0.2))
    with pytest.raises(ValueError):
        RoutingPolicy(max_escalations=-1)
