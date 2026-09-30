"""Veredito router (app/services/verdict.py, app/gateway/optimizer.py hook). No network."""
from __future__ import annotations

import json

import pytest

from app.gateway.optimizer import MemoryOptimizer
from app.services.verdict import decide
from config.optimizer import OptimizerConfig, verdict_enabled_default

from tests.test_optimizer import make_gw


# -- decide() is pure bookkeeping over the existing router ------------------------------------
def test_decide_never_overrides_route_for():
    cfg = OptimizerConfig().with_(verdict_enabled=True, route_complex="graphify")
    for complexity in ("SIMPLE", "MEDIUM", "COMPLEX", "AMBIGUOUS"):
        for size in (None, 0, 5, 15, 16, 49, 50, 500):
            pipeline, _ = decide("q", complexity, size, cfg)
            assert pipeline == cfg.route_for(complexity)


def test_decide_buckets_by_configured_thresholds():
    cfg = OptimizerConfig().with_(verdict_enabled=True)
    _, small = decide("q", "SIMPLE", cfg.verdict_small_max, cfg)
    _, medium = decide("q", "SIMPLE", cfg.verdict_small_max + 1, cfg)
    _, large = decide("q", "SIMPLE", cfg.verdict_large_min, cfg)
    _, unknown = decide("q", "SIMPLE", None, cfg)
    assert small.split(":")[2] == "small"
    assert medium.split(":")[2] == "medium"
    assert large.split(":")[2] == "large"
    assert unknown == "verdict:SIMPLE:size_unknown"


# -- explicit pipeline requests never go through the verdict (§1.2, no exception) --------------
@pytest.mark.parametrize("pipeline", ["baseline", "graphify", "graphify_jev", "graphify_jev_opt"])
def test_explicit_pipeline_disables_verdict_for_every_concrete_pipeline(pipeline):
    opt = MemoryOptimizer(OptimizerConfig().with_(verdict_enabled=True))
    plan = opt.plan("qual o driver?", pipeline)
    assert plan.pipeline == pipeline
    assert plan.reason == "explicit"
    assert plan.verdict_size_estimate is None


# -- flag off: auto behaves exactly like before the feature existed ----------------------------
def test_verdict_disabled_by_default_leaves_auto_unchanged():
    opt = MemoryOptimizer(OptimizerConfig())
    assert opt.cfg.verdict_enabled is False
    plan = opt.plan("qual o driver?", "auto")
    assert plan.reason.startswith("auto:")
    assert plan.verdict_size_estimate is None


def test_verdict_enabled_uses_baseline_count_as_size_estimate(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path, verdict_enabled=True)
    plan = gw.optimizer.plan("stack backend FastAPI", "auto", gw)
    assert plan.pipeline == gw.optimizer.cfg.route_for(plan.profile.complexity)
    assert plan.reason.startswith("verdict:")
    assert plan.verdict_size_estimate == gw.baseline.count("stack backend FastAPI")


def test_verdict_size_estimate_none_without_gw():
    opt = MemoryOptimizer(OptimizerConfig().with_(verdict_enabled=True))
    plan = opt.plan("qual o driver?", "auto")
    assert plan.verdict_size_estimate is None
    assert plan.reason.endswith("size_unknown")


def test_verdict_size_probe_failure_never_blocks_search(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path, verdict_enabled=True)

    class Boom:
        def count(self, query):
            raise RuntimeError("boom")

    gw.baseline = Boom()
    plan = gw.optimizer.plan("stack backend FastAPI", "auto", gw)
    assert plan.verdict_size_estimate is None
    assert plan.pipeline == gw.optimizer.cfg.route_for(plan.profile.complexity)


# -- end-to-end: metrics_json carries the verdict fields only when the flag is on ---------------
def test_search_records_verdict_metrics_when_enabled(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path, verdict_enabled=True)
    r = gw.search("stack backend FastAPI", persist=False)
    m = r.metrics
    assert m["verdict_pipeline_chosen"] == r.pipeline
    assert m["verdict_reason"].startswith("verdict:")
    assert m["verdict_size_estimate"] is not None


def test_search_omits_verdict_metrics_when_disabled(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path)
    r = gw.search("stack backend FastAPI", persist=False)
    m = r.metrics
    assert "verdict_pipeline_chosen" not in m
    assert "verdict_reason" not in m
    assert "verdict_size_estimate" not in m


def test_search_omits_verdict_metrics_for_explicit_pipeline_even_when_enabled(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path, verdict_enabled=True)
    r = gw.search("stack backend FastAPI", pipeline="baseline", persist=False)
    assert "verdict_pipeline_chosen" not in r.metrics


# -- BaselineIndex.count() ------------------------------------------------------------------
def test_baseline_count_matches_search_upper_bound(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path)
    n = gw.baseline.count("stack backend FastAPI")
    assert n >= 0
    assert n == len(gw.baseline.search("stack backend FastAPI", limit=10_000))


def test_baseline_count_empty_query_is_zero(tiny_vault, tmp_path):
    gw = make_gw(tiny_vault, tmp_path)
    assert gw.baseline.count("") == 0


# -- config: local_settings.json precedence over env, tolerant of missing/bad file --------------
def test_verdict_enabled_default_env_when_no_local_file(monkeypatch):
    import config.optimizer as mod

    monkeypatch.setattr(mod, "LOCAL_SETTINGS_PATH", mod.PROJECT_ROOT / "config" / "does-not-exist.json")
    monkeypatch.setenv("MG_VERDICT_ENABLED", "true")
    assert verdict_enabled_default() is True
    monkeypatch.setenv("MG_VERDICT_ENABLED", "false")
    assert verdict_enabled_default() is False


def test_verdict_enabled_local_file_overrides_env(tmp_path, monkeypatch):
    import config.optimizer as mod

    local = tmp_path / "local_settings.json"
    local.write_text(json.dumps({"verdict_enabled": True}), encoding="utf-8")
    monkeypatch.setattr(mod, "LOCAL_SETTINGS_PATH", local)
    monkeypatch.setenv("MG_VERDICT_ENABLED", "false")
    assert verdict_enabled_default() is True


def test_verdict_enabled_tolerant_of_malformed_local_file(tmp_path, monkeypatch):
    import config.optimizer as mod

    local = tmp_path / "local_settings.json"
    local.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(mod, "LOCAL_SETTINGS_PATH", local)
    monkeypatch.setenv("MG_VERDICT_ENABLED", "true")
    assert verdict_enabled_default() is True
