"""§5.2/§1.3 da proposta 2026-09-28: every interface must agree on the same pipeline list, and
`graphify_jev_opt` must be reachable and correctly accounted for everywhere `graphify_jev` was."""
from __future__ import annotations

from app.benchmark.report import PIPES
from app.benchmark.runner import estimate_plan
from app.retrieval.pipelines import PIPELINE_FUNCS
from app.schemas.models import DEFAULT_EXPLICIT_PIPELINE, JEV_PIPELINES, PIPELINES


def test_pipeline_funcs_matches_the_centralized_pipeline_list():
    assert set(PIPELINE_FUNCS) == set(PIPELINES)


def test_report_pipes_is_the_centralized_pipeline_list():
    assert PIPES == PIPELINES


def test_default_explicit_pipeline_is_the_cascade_not_the_frozen_reference():
    assert DEFAULT_EXPLICIT_PIPELINE == "graphify_jev_opt"
    assert DEFAULT_EXPLICIT_PIPELINE in PIPELINES
    assert "graphify_jev" in PIPELINES  # frozen reference stays executable


def test_estimate_plan_counts_jev_runs_for_the_cascade_too():
    """Both graphify_jev and graphify_jev_opt pay the judge; a plan for both must count 2 judge
    runs per question, not 1 (the pre-cascade formula only ever checked for "graphify_jev")."""
    only_frozen = estimate_plan(10, ["graphify_jev"], [], 1)
    both = estimate_plan(10, ["graphify_jev", "graphify_jev_opt"], [], 1)
    neither = estimate_plan(10, ["baseline", "graphify"], [], 1)
    assert only_frozen["jev_runs"] == 10
    assert both["jev_runs"] == 20
    assert neither["jev_runs"] == 0
    assert set(JEV_PIPELINES) == {"graphify_jev", "graphify_jev_opt"}
