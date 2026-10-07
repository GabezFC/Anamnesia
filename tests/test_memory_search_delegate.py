"""memory_search mode='delegate' -> Orchestrator.submit (FakeLauncher; no model, no network, no PTY)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.orchestration import delegate as dg
from app.orchestration.launchers import FakeLauncher
from app.orchestration.orchestrator import Orchestrator
from app.routing import answer as ans
from tests.orch_helpers import cfg, project, three


class GW:
    def __init__(self):
        self.db = SimpleNamespace(update_run_answer=lambda *a, **k: None)


def fake_result():
    return SimpleNamespace(query="Corrigir o parser", run_id="x1", metrics={"scope": "global"}, context="ctx")


@pytest.fixture
def orch(tmp_path, monkeypatch):
    o = Orchestrator(FakeLauncher(), registry=three(tmp_path), config=cfg(), sync=True)
    monkeypatch.setattr(dg, "get_orchestrator", lambda: o)
    monkeypatch.delenv("ANAMNESIA_DELEGATE", raising=False)
    monkeypatch.delenv("MG_PROJECT_PATH", raising=False)
    return o


def test_disabled_keeps_legacy_fallback(orch, tmp_path, monkeypatch):
    monkeypatch.setenv("MG_PROJECT_PATH", str(project(tmp_path)))
    out = ans.apply_mode(GW(), fake_result(), "delegate")
    assert out["mode_used"] == "context" and out["fallback_reason"] == "delegate_not_implemented"
    assert out["delegate_status"] == "delegate_disabled" and "delegate" not in out
    assert orch.launcher.calls == []


def test_enabled_without_project(orch, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DELEGATE", "1")
    out = ans.apply_mode(GW(), fake_result(), "delegate")
    assert out["mode_used"] == "context" and out["fallback_reason"] == "delegate_no_project"


def test_enabled_missing_dir_is_no_project(orch, tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DELEGATE", "1")
    monkeypatch.setenv("MG_PROJECT_PATH", str(tmp_path / "nope"))
    assert ans.apply_mode(GW(), fake_result(), "delegate")["fallback_reason"] == "delegate_no_project"


def test_enabled_submits_run(orch, tmp_path, monkeypatch):
    d = project(tmp_path)
    monkeypatch.setenv("ANAMNESIA_DELEGATE", "1")
    monkeypatch.setenv("MG_PROJECT_PATH", str(d))
    out = ans.apply_mode(GW(), fake_result(), "delegate")
    assert out["mode_used"] == "delegate" and "fallback_reason" not in out
    info = out["delegate"]
    assert info["preset"] == "balanced" and info["run_id"]
    st = dg.get_delegate_status(info["run_id"], d)
    assert st["state"] == "done" and [s["role"] for s in st["steps"]] == ["researcher", "implementer", "reviewer"]
    assert orch.get(info["run_id"], d).task_text().strip() == "Corrigir o parser"


def test_submit_error_falls_back_without_raising(orch, tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DELEGATE", "1")
    monkeypatch.setenv("MG_PROJECT_PATH", str(project(tmp_path)))
    monkeypatch.setenv("ANAMNESIA_DELEGATE_PRESET", "bogus")
    out = ans.apply_mode(GW(), fake_result(), "delegate")
    assert out["mode_used"] == "context" and out["fallback_reason"].startswith("delegate_error:")


def test_scope_resolves_registered_project(tmp_path, monkeypatch):
    d = project(tmp_path)
    monkeypatch.delenv("MG_PROJECT_PATH", raising=False)
    import app.api.workspace as ws
    reg = SimpleNamespace(list=lambda: [SimpleNamespace(id="abc", name="MeuProj", path=str(d))])
    monkeypatch.setattr(ws, "get_registry", lambda: reg)
    assert dg.resolve_project_path("projeto:meuproj") == str(d)
    assert dg.resolve_project_path("projeto:outro") is None
    assert dg.resolve_project_path(None) is None


def test_mcp_exposes_delegate_fields(orch, tmp_path, monkeypatch):
    from app.mcp import server as mod
    monkeypatch.setenv("ANAMNESIA_DELEGATE", "1")
    monkeypatch.setenv("MG_PROJECT_PATH", str(project(tmp_path)))
    extras = ans.apply_mode(GW(), fake_result(), "delegate")
    out = mod._merge({"run_id": "x1", "context": "ctx"}, extras)
    assert out["delegate"]["run_id"] and out["mode_used"] == "delegate" and out["context"] == "ctx"


def test_context_mode_unchanged():
    assert ans.apply_mode(GW(), fake_result(), "context") == {}
