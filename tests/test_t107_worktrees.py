"""T10.7: git worktree list/add/remove via API, real temporary git repo."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.services import ui_challenge
from app.terminals import worktrees as wt
from app.terminals.backend import FakePtyBackend
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import ProjectRegistry

H = {"X-MG-Token": "test-token-abc123"}
ORIGIN = "http://127.0.0.1:8000"


def git(cwd, *a):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e.x")
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=cwd, check=True, capture_output=True,
                          text=True, env=env).stdout


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("MG_LOCAL_TOKEN", "test-token-abc123")
    monkeypatch.delenv(ws_api.ALLOW_REMOTE_ENV, raising=False)
    monkeypatch.delenv("MG_HOST", raising=False)
    mgr = TerminalManager(backend=FakePtyBackend(), environ={"PATH": "/bin"})
    reg = ProjectRegistry(tmp_path / "a.db")
    app = FastAPI()
    app.include_router(ws_api.router)
    app.dependency_overrides[ws_api.get_manager] = lambda: mgr
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    app.dependency_overrides[ws_api.get_profiles] = lambda: {
        "shell": Profile(id="shell", name="s", command=sys.executable)}
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    c = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    pid = c.post("/api/projects", json={"name": "repo", "path": str(repo)}, headers=H).json()["id"]
    yield type("Ctx", (), dict(client=c, repo=repo, base=f"/api/projects/{pid}/worktrees"))
    mgr.close_all()


def _add(ctx, branch="feat/x"):
    r = ctx.client.post(ctx.base, json={"branch": branch}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()


def test_add_is_managed_and_listed(ctx):
    w = _add(ctx)
    assert os.path.isdir(w["path"]) and w["managed"] and w["branch"] == "feat/x"
    assert os.path.normcase(w["path"]).startswith(os.path.normcase(str(wt.managed_root(str(ctx.repo)))))
    ids = [x["id"] for x in ctx.client.get(ctx.base, headers=H).json()["worktrees"]]
    assert w["id"] in ids and len(ids) == 2


def test_remove_requires_confirm(ctx):
    w = _add(ctx)
    r = ctx.client.delete(f"{ctx.base}/{w['id']}", headers=H)
    assert r.status_code == 403
    assert os.path.isdir(w["path"])
    r = ctx.client.delete(f"{ctx.base}/{w['id']}", params={"confirm": "true"}, headers=H)
    assert r.status_code == 200 and not os.path.exists(w["path"])


def test_remove_requires_header_when_enforced(ctx, monkeypatch):
    monkeypatch.setenv("MG_SHELL_CONFIRM", "enforce")
    w = _add(ctx)
    url = f"{ctx.base}/{w['id']}"
    r = ctx.client.delete(url, params={"confirm": "true"}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "confirm_required"
    assert os.path.isdir(w["path"])
    r = ctx.client.delete(url, params={"confirm": "true"},
                          headers={**H, "X-MG-Confirm": ui_challenge.ui_cookie_value()})
    assert r.status_code == 200


def test_remove_refuses_dirty_unless_force(ctx):
    w = _add(ctx)
    with open(os.path.join(w["path"], "a.txt"), "w", encoding="utf-8") as f:
        f.write("changed\n")
    url = f"{ctx.base}/{w['id']}"
    r = ctx.client.delete(url, params={"confirm": "true"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "dirty"
    assert os.path.isdir(w["path"])
    r = ctx.client.delete(url, params={"confirm": "true", "force": "true"}, headers=H)
    assert r.status_code == 200 and not os.path.exists(w["path"])


def test_primary_and_unknown_ids_cannot_be_removed(ctx):
    (primary,) = ctx.client.get(ctx.base, headers=H).json()["worktrees"]
    r = ctx.client.delete(f"{ctx.base}/{primary['id']}", params={"confirm": "true", "force": "true"}, headers=H)
    assert r.status_code == 403 and ctx.repo.is_dir()
    r = ctx.client.delete(f"{ctx.base}/nope", params={"confirm": "true"}, headers=H)
    assert r.status_code == 404


def test_worktree_outside_managed_root_is_not_removable(ctx, tmp_path):
    other = tmp_path / "elsewhere"
    git(ctx.repo, "worktree", "add", "-q", "-b", "ext", str(other))
    ext = next(w for w in ctx.client.get(ctx.base, headers=H).json()["worktrees"] if w["branch"] == "ext")
    r = ctx.client.delete(f"{ctx.base}/{ext['id']}", params={"confirm": "true", "force": "true"}, headers=H)
    assert r.status_code == 403 and other.is_dir()


@pytest.mark.parametrize("bad", ["../escape", "a..b", "-x", "a b", "x/", "/abs", "a\\b", "x.lock"])
def test_branch_names_cannot_escape(ctx, bad):
    r = ctx.client.post(ctx.base, json={"branch": bad}, headers=H)
    assert r.status_code == 422, (bad, r.text)


def test_duplicate_branch_conflicts_and_auth_required(ctx):
    _add(ctx)
    assert ctx.client.post(ctx.base, json={"branch": "feat/x"}, headers=H).status_code == 409
    assert ctx.client.post(ctx.base, json={"branch": "y"}).status_code == 403
