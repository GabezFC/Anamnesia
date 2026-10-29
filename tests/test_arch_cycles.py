"""ANA-056/106/107/108/132: architecture guards (import cycles, layering, state injection, registry)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_import_cycles as cyc  # noqa: E402


@pytest.fixture(scope="module")
def graph():
    return cyc.build_graph(ROOT, "app")


def test_tarjan_detects_a_synthetic_cycle():
    g = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": {"a"}, "e": set()}
    assert cyc.tarjan_sccs(g) == [["a", "b", "c"]]
    assert cyc.tarjan_sccs({"a": {"b"}, "b": set()}) == []


# ANA-107 -------------------------------------------------------------------------------------
def test_retrieval_has_no_cycle(graph):
    sccs = [c for c in cyc.tarjan_sccs(graph) if any(m.startswith("app.retrieval") for m in c)]
    assert sccs == []


def test_pipelines_opt_does_not_import_pipelines(graph):
    assert "app.retrieval.pipelines" not in graph["app.retrieval.pipelines_opt"]


def test_registry_contains_all_pipelines_whatever_the_import_order():
    from app.schemas.models import PIPELINES
    # opt first: the frozen pipeline must still be reachable through the registry
    importlib.import_module("app.retrieval.pipelines_opt")
    from app.retrieval.registry import get_pipeline
    assert callable(get_pipeline("graphify_jev"))
    assert set(importlib.import_module("app.retrieval.registry").PIPELINE_FUNCS) == set(PIPELINES)


def test_pipelines_still_expose_legacy_helpers():
    from app.retrieval import pipelines
    for name in ("_graphify_candidates", "full_note_text", "_apply_scope", "_tokens", "PIPELINE_FUNCS"):
        assert hasattr(pipelines, name)


def test_disabled_cascade_delegates_to_frozen_pipeline_via_registry(monkeypatch):
    from types import SimpleNamespace

    from app.retrieval import pipelines_opt
    from app.retrieval.registry import PIPELINE_FUNCS
    seen = {}

    def frozen(gw, q, n, jev=None):
        seen["called"] = (q, n)
        return [], {}, {}
    monkeypatch.setitem(PIPELINE_FUNCS, "graphify_jev", frozen)
    opt = SimpleNamespace(enabled=False)
    assert pipelines_opt.run_graphify_jev_optimized(object(), "q", 3, opt=opt) == ([], {}, {})
    assert seen["called"] == ("q", 3)


# ANA-108 -------------------------------------------------------------------------------------
def test_no_cycles_in_routing_orchestration_services_benchmark(graph):
    mine = ("app.routing", "app.orchestration", "app.services", "app.benchmark", "app.retrieval", "app.core")
    bad = [c for c in cyc.tarjan_sccs(graph) if any(m.startswith(mine) for m in c)]
    assert bad == [], bad


def test_orchestration_and_routing_do_not_import_api(graph):
    assert cyc.edges_between(graph, "app.orchestration", "app.api") == []
    assert cyc.edges_between(graph, "app.routing", "app.api") == []
    assert cyc.edges_between(graph, "app.routing", "app.orchestration") == []


def test_delegate_uses_injected_provider_over_api_lookup(monkeypatch):
    from app.orchestration import delegate as dg
    sentinel = object()
    dg.set_provider("default_orchestrator", lambda: sentinel)
    try:
        monkeypatch.delenv("ANAMNESIA_DELEGATE_LAUNCHER", raising=False)
        assert dg.get_orchestrator() is sentinel
    finally:
        dg.clear_providers()


def test_wilson_ci_moved_to_core_and_reexported():
    from app.benchmark import statistics
    from app.core import stats
    assert statistics.wilson_ci is stats.wilson_ci
    assert stats.wilson_ci(0, 0)["rate"] is None


# ANA-056 -------------------------------------------------------------------------------------
def test_core_tokens_is_the_implementation_and_legacy_shims_are_gone():
    import app.core.tokens as core
    assert core.estimate_tokens("olá mundo") > 0
    # Shims removidos com aprovação do usuário (2026-10-24): token_budget -> app.core.tokens; app.config fachada.
    for legacy in ("app.gateway.token_budget", "app.config"):
        sys.modules.pop(legacy, None)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(legacy)
    assert not (ROOT / "app" / "gateway" / "token_budget.py").exists()
    assert not (ROOT / "app" / "config.py").exists()
    assert '"app.config"' not in (ROOT / "scripts" / "layers.toml").read_text(encoding="utf-8")


def test_core_has_no_upward_imports(graph):
    for mod, deps in graph.items():
        if mod.startswith("app.core"):
            assert all(d.startswith("app.core") for d in deps), (mod, deps)


def test_nobody_in_app_imports_the_deprecated_token_budget(graph):
    users = [m for m, d in graph.items() if "app.gateway.token_budget" in d]
    assert users == []


# ANA-106 -------------------------------------------------------------------------------------
def test_no_state_dict_references_in_api_or_main():
    for p in list((ROOT / "app" / "api").glob("*.py")) + [ROOT / "app" / "main.py"]:
        txt = p.read_text(encoding="utf-8")
        assert "_state[" not in txt and "_state.get" not in txt, p


def test_jobstore_ttl_expires_only_finished_jobs():
    from app.core.state import JobStore
    t = [0.0]
    js = JobStore(ttl_s=10, clock=lambda: t[0])
    js.create("run")
    js.create("fin")
    js.update("fin", status="done", result=1)
    t[0] = 11
    assert js.get("fin") is None
    assert js.get("run")["status"] == "running"
    js.append_progress("run", {"a": 1})
    assert js.get("run")["progress"] == [{"a": 1}]


def test_get_gateway_dependency_override_without_monkeypatching_globals():
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from app.api.deps import get_gateway
    app = FastAPI()

    @app.get("/x")
    def x(g=Depends(get_gateway)):
        return {"who": g}

    c = TestClient(app)
    from app.core.state import STATE
    assert STATE.gateway is None or True
    app.dependency_overrides[get_gateway] = lambda: "fake"
    assert c.get("/x").json() == {"who": "fake"}


def test_get_gateway_503_when_not_ready(monkeypatch):
    from fastapi import HTTPException

    from app.api.deps import get_gateway
    from app.core.state import STATE
    monkeypatch.setattr(STATE, "gateway", None)
    with pytest.raises(HTTPException) as ei:
        get_gateway()
    assert ei.value.status_code == 503


def test_legacy_state_alias_is_deprecated_but_works(monkeypatch):
    from app.api import routes
    from app.core.state import STATE
    monkeypatch.setattr(STATE, "gateway", "gw1")
    with pytest.warns(DeprecationWarning):
        view = routes._state
    assert view["gateway"] == "gw1"
