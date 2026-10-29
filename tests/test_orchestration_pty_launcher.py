"""Launcher PTY interno: remover projeto NAO depende do manager; get_manager e do launcher; perfil do delegate.

C01 (opcao a): o PTY e so launcher interno (sem rotas/UI). `DELETE /api/projects/{id}` desvincula o cadastro,
nunca apaga a pasta, e nunca instancia o TerminalManager.
"""
from __future__ import annotations

import sys
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.orchestration import delegate, pty_launcher
from app.terminals.backend import FakePtyBackend
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import Project, ProjectRegistry

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN, "Origin": ORIGIN, "Referer": ORIGIN + "/"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ANAMNESIA_PROJECT_GUARD", "off")
    monkeypatch.setattr(pty_launcher, "_manager", None)       # manager INEXISTENTE
    app = FastAPI()
    app.include_router(ws_api.router)
    reg = ProjectRegistry(tmp_path / "a.db")
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    proj = tmp_path / "repo"
    proj.mkdir()
    (proj / "keep.txt").write_text("x")
    c = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    r = c.post("/api/projects", json={"name": "repo", "path": str(proj)}, headers=H)
    assert r.status_code == 201, r.text
    return type("A", (), dict(c=c, pid=r.json()["id"], proj=proj, reg=reg))


def test_workspace_module_has_no_terminal_manager_dependency():
    assert not hasattr(ws_api, "get_manager") and not hasattr(ws_api, "TerminalManager")
    assert not any(isinstance(r.path, str) and "/sessions" in r.path for r in ws_api.router.routes)


def test_register_then_remove_without_any_manager(api):
    assert pty_launcher.peek_manager() is None
    r = api.c.delete(f"/api/projects/{api.pid}", headers=H)
    assert r.status_code == 200 and r.json()["removed"] is True and r.json()["files_untouched"] is True
    assert pty_launcher.peek_manager() is None                 # remover nao instancia o manager
    assert (api.proj / "keep.txt").read_text() == "x"          # a pasta nunca e apagada
    assert api.c.delete(f"/api/projects/{api.pid}", headers=H).status_code == 404


def test_remove_closes_only_that_projects_sessions_when_manager_exists(api, monkeypatch, tmp_path):
    mgr = TerminalManager(backend=FakePtyBackend(), environ={"PATH": "/bin"})
    monkeypatch.setattr(pty_launcher, "_manager", mgr)
    prof = Profile(id="agent", name="A", command=sys.executable)
    d = tmp_path / "other"
    d.mkdir()
    mine = mgr.create(Project(api.pid, "repo", str(api.proj), time.time()), prof)
    other = mgr.create(Project("zzz", "other", str(d), time.time()), prof)
    try:
        assert api.c.delete(f"/api/projects/{api.pid}", headers=H).status_code == 200
        ids = {s.id for s in mgr.list()}
        assert mine.id not in ids and other.id in ids
    finally:
        mgr.close_all()


def test_close_project_sessions_swallows_manager_errors(monkeypatch):
    class Boom:
        def list(self):
            raise RuntimeError("x")
    monkeypatch.setattr(pty_launcher, "_manager", Boom())
    assert pty_launcher.close_project_sessions("p") == 0


def test_get_manager_is_lazy_singleton_owned_by_launcher(monkeypatch):
    monkeypatch.setattr(pty_launcher, "_manager", None)
    monkeypatch.setattr("app.terminals.manager.default_backend", lambda: FakePtyBackend())
    a = pty_launcher.get_manager()
    try:
        assert pty_launcher.get_manager() is a and pty_launcher.peek_manager() is a
        assert isinstance(a, TerminalManager)
    finally:
        a.close_all()
        pty_launcher.reset_for_tests()


@pytest.fixture
def clean_delegate(monkeypatch):
    monkeypatch.setattr(delegate, "_term_orch", None)
    monkeypatch.delenv("ANAMNESIA_DELEGATE_PROFILE", raising=False)
    monkeypatch.setenv("ANAMNESIA_DELEGATE_LAUNCHER", "terminal")


def test_terminal_mode_without_profile_is_refused_not_silently_shell(clean_delegate):
    with pytest.raises(delegate.DelegateError) as ei:
        delegate.get_orchestrator()
    assert ei.value.reason_code == "profile_not_agent"


def test_terminal_mode_with_agent_profile_builds_launcher_over_pty_launcher_manager(clean_delegate, monkeypatch):
    mgr = TerminalManager(backend=FakePtyBackend(), environ={"PATH": "/bin"})
    monkeypatch.setattr(pty_launcher, "_manager", mgr)
    monkeypatch.setenv("ANAMNESIA_DELEGATE_PROFILE", "claude-code")
    try:
        o = delegate.get_orchestrator()
        assert type(o.launcher).__name__ == "TerminalLauncher" and o.launcher.manager is mgr
        assert o.profile_id == "claude-code" and o.launcher.default_profile_id == "claude-code"
    finally:
        monkeypatch.setattr(delegate, "_term_orch", None)
        mgr.close_all()
