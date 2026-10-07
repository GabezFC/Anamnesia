"""Terminal hardening: content search (T10.8), git worktrees (T10.7), janitor, Ctrl+C forwarding."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workspace as ws_api
from app.terminals import worktrees as wt
from app.terminals.backend import FakePtyBackend
from app.terminals.manager import TerminalManager
from app.terminals.profiles import Profile
from app.terminals.projects import Project, ProjectRegistry, search_content

TOKEN = "test-token-abc123"
ORIGIN = "http://127.0.0.1:8000"
H = {"X-MG-Token": TOKEN}


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------ content search
@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("import os\nNeedle here\nother\n", encoding="utf-8")
    (root / "b.txt").write_text("nothing\nxx needle yy\n", encoding="utf-8")
    (root / "bin.dat").write_bytes(b"\x00\x01needle\x00")
    (root / "big.txt").write_text("needle\n" + "x" * 2000, encoding="utf-8")
    for d in (".git", "node_modules", ".venv"):
        (root / d).mkdir()
        (root / d / "f.txt").write_text("needle", encoding="utf-8")
    return root


def test_content_search_hits_lines_and_skips(tree):
    r = search_content(str(tree), "needle", max_file_bytes=1000)
    hits = {(h["path"], h["line"]) for h in r["results"]}
    assert hits == {("src/a.py", 2), ("b.txt", 2)}  # case-insensitive; binary/big/skipped dirs absent
    assert all(len(h["snippet"]) <= 170 for h in r["results"])
    assert "Needle here" in next(h for h in r["results"] if h["path"] == "src/a.py")["snippet"]
    assert r["truncated"] is False


def test_content_search_caps_and_budgets(tree):
    (tree / "many.txt").write_text("needle\n" * 50, encoding="utf-8")
    r = search_content(str(tree), "needle", cap=5)
    assert len(r["results"]) == 5 and r["truncated"] is True
    r = search_content(str(tree), "needle", max_total_bytes=1)
    assert r["truncated"] is True
    ticks = iter(range(0, 1000, 10))
    r = search_content(str(tree), "needle", max_seconds=5, clock=lambda: next(ticks))
    assert r["truncated"] is True  # fake clock jumps past the deadline


def test_content_search_binary_sniff_invalid_utf8(tree):
    (tree / "latin.txt").write_bytes(b"caf\xe9 needle\n" + b"\xff\xfe" * 10)
    r = search_content(str(tree), "needle", max_file_bytes=1000)
    assert "latin.txt" not in {h["path"] for h in r["results"]}


def test_content_search_never_follows_symlinks_or_escapes(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle", encoding="utf-8")
    try:
        os.symlink(outside, tree / "linkdir", target_is_directory=True)
        os.symlink(outside / "secret.txt", tree / "linkfile.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted here")
    r = search_content(str(tree), "needle", max_file_bytes=1000)
    assert all("secret" not in h["path"] and "link" not in h["path"] for h in r["results"])
    from app.terminals.projects import PathEscapeError

    for bad in ("..", "../outside", str(outside)):
        with pytest.raises(PathEscapeError):
            search_content(str(tree), "needle", bad)


# ------------------------------------------------------------------ API fixture
@pytest.fixture
def ctx(monkeypatch, tmp_path):
    monkeypatch.setenv("MG_LOCAL_TOKEN", TOKEN)
    monkeypatch.delenv("MG_HOST", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv(ws_api.ALLOW_REMOTE_ENV, raising=False)
    fake = FakePtyBackend()
    mgr = TerminalManager(backend=fake, max_sessions=4, environ={"PATH": "/bin"})
    reg = ProjectRegistry(tmp_path / "anamnesia.db")
    profiles = {"shell": Profile(id="shell", name="Shell", command=sys.executable, kind="shell")}
    app = FastAPI()
    app.include_router(ws_api.router)
    app.dependency_overrides[ws_api.get_manager] = lambda: mgr
    app.dependency_overrides[ws_api.get_registry] = lambda: reg
    app.dependency_overrides[ws_api.get_profiles] = lambda: profiles
    proj_dir = tmp_path / "work"
    proj_dir.mkdir()
    (proj_dir / "f.txt").write_text("hello needle\n", encoding="utf-8")
    client = TestClient(app, client=("127.0.0.1", 51234), base_url=ORIGIN)
    yield type("Ctx", (), dict(client=client, mgr=mgr, fake=fake, proj_dir=proj_dir))
    mgr.close_all()


def _add(c):
    r = c.client.post("/api/projects", json={"name": "w", "path": str(c.proj_dir)}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_api_content_search(ctx):
    pid = _add(ctx)
    r = ctx.client.get(f"/api/projects/{pid}/files", params={"q": "NEEDLE", "content": 1}, headers=H)
    assert r.status_code == 200
    assert r.json()["results"] == [{"path": "f.txt", "line": 1, "snippet": "hello needle"}]
    r = ctx.client.get(f"/api/projects/{pid}/files", params={"q": "needle", "content": 1, "path": ".."}, headers=H)
    assert r.status_code == 403 and r.json()["error"]["code"] == "path_escape"
    assert ctx.client.get(f"/api/projects/{pid}/files", params={"q": "f", "content": 1}).status_code == 403  # no token
    # name search still works without content=1
    r = ctx.client.get(f"/api/projects/{pid}/files", params={"q": "f.txt"}, headers=H)
    assert r.status_code == 200 and "mode" not in r.json()


# ------------------------------------------------------------------ worktrees (real git)
def _git(cwd, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e.x", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@e.x")
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env=env).stdout


@pytest.fixture
def repo(ctx):
    d = ctx.proj_dir
    _git(d, "init", "-q")
    _git(d, "add", ".")
    _git(d, "commit", "-q", "-m", "init")
    return d


def test_worktree_lifecycle_and_sessions(ctx, repo):
    pid = _add(ctx)
    base = f"/api/projects/{pid}/worktrees"
    r = ctx.client.get(base, headers=H)
    assert r.status_code == 200
    (primary,) = r.json()["worktrees"]
    assert primary["primary"] is True and primary["managed"] is False

    r = ctx.client.post(base, json={"branch": "feat/x"}, headers=H)
    assert r.status_code == 201, r.text
    w = r.json()
    expected = repo.parent / wt.WORKTREES_DIRNAME / "w-feat-x"
    assert os.path.realpath(w["path"]) == os.path.realpath(expected) and expected.is_dir()
    assert w["branch"] == "feat/x" and w["managed"] and not w["primary"]
    assert (expected / "f.txt").exists()

    # duplicate branch -> 409
    assert ctx.client.post(base, json={"branch": "feat/x"}, headers=H).status_code == 409

    # session cwd = worktree
    r = ctx.client.post("/api/sessions", json={"project": pid, "profile": "shell", "worktree_id": w["id"]}, headers=H)
    assert r.status_code == 201, r.text
    assert os.path.realpath(ctx.fake.spawned[-1].cwd) == os.path.realpath(expected)
    assert r.json()["session"]["worktree_id"] == w["id"]
    sid = r.json()["session_id"]
    r = ctx.client.post("/api/sessions", json={"project": pid, "worktree_id": "nope"}, headers=H)
    assert r.status_code == 404

    # delete: needs confirm; primary never; dirty needs force
    assert ctx.client.delete(f"{base}/{w['id']}", headers=H).status_code == 403
    r = ctx.client.delete(f"{base}/{primary['id']}", params={"confirm": "true", "force": "true"}, headers=H)
    assert r.status_code == 403 and repo.is_dir()
    (expected / "dirty.txt").write_text("wip", encoding="utf-8")
    r = ctx.client.delete(f"{base}/{w['id']}", params={"confirm": "true"}, headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "dirty" and expected.is_dir()
    r = ctx.client.delete(f"{base}/{w['id']}", params={"confirm": "true", "force": "true"}, headers=H)
    assert r.status_code == 200, r.text
    assert not expected.exists()
    assert [x["primary"] for x in ctx.client.get(base, headers=H).json()["worktrees"]] == [True]
    assert ctx.fake.spawned[-1].terminated == 1 and sid not in [s.id for s in ctx.mgr.list()]  # session closed


def test_worktree_clean_delete_without_force(ctx, repo):
    pid = _add(ctx)
    base = f"/api/projects/{pid}/worktrees"
    w = ctx.client.post(base, json={"branch": "clean"}, headers=H).json()
    r = ctx.client.delete(f"{base}/{w['id']}", params={"confirm": "true"}, headers=H)
    assert r.status_code == 200 and not os.path.exists(w["path"])


def test_worktree_existing_branch_is_checked_out(ctx, repo):
    _git(repo, "branch", "old")
    pid = _add(ctx)
    r = ctx.client.post(f"/api/projects/{pid}/worktrees", json={"branch": "old"}, headers=H)
    assert r.status_code == 201 and r.json()["branch"] == "old"


@pytest.mark.parametrize("bad", ["-x", "--detach", "a b", "a;rm -rf /", "../x", "a/../b", "x.lock", "a//b", "$(id)",
                                 "", "a/.hidden", "é", "x" * 80, "/abs", "a\nb"])
def test_worktree_rejects_bad_branch_names(ctx, repo, bad):
    pid = _add(ctx)
    r = ctx.client.post(f"/api/projects/{pid}/worktrees", json={"branch": bad}, headers=H)
    assert r.status_code in (422,), (bad, r.status_code, r.text)
    assert not (repo.parent / wt.WORKTREES_DIRNAME).exists()


def test_worktrees_non_git_project_and_auth(ctx):
    pid = _add(ctx)
    r = ctx.client.get(f"/api/projects/{pid}/worktrees", headers=H)
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_a_git_repo"
    assert ctx.client.get(f"/api/projects/{pid}/worktrees").status_code == 403
    assert ctx.client.get("/api/projects/zzz/worktrees", headers=H).status_code == 404


def test_cannot_delete_unmanaged_worktree(ctx, repo, tmp_path):
    other = tmp_path / "elsewhere"
    _git(repo, "worktree", "add", "-q", "-b", "ext", str(other))
    pid = _add(ctx)
    base = f"/api/projects/{pid}/worktrees"
    ext = next(w for w in ctx.client.get(base, headers=H).json()["worktrees"] if w["branch"] == "ext")
    assert ext["managed"] is False
    r = ctx.client.delete(f"{base}/{ext['id']}", params={"confirm": "true", "force": "true"}, headers=H)
    assert r.status_code == 403 and other.is_dir()


# ------------------------------------------------------------------ janitor (fake clock)
def test_janitor_reaps_idle_session_with_fake_clock(tmp_path):
    now = [1000.0]
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    fake = FakePtyBackend()
    m = TerminalManager(backend=fake, idle_seconds=10, clock=lambda: now[0], environ={"PATH": "/bin"},
                        janitor_interval=0.01)
    try:
        assert m._janitor is None  # lazy: nothing before the first session
        s = m.create(proj, prof)
        assert m._janitor is not None and m._janitor.is_alive() and m._janitor.daemon
        time.sleep(0.1)
        assert s.state == "active" and fake.spawned[0].terminated == 0  # not idle long enough
        now[0] += 11
        assert wait_for(lambda: fake.spawned[0].terminated > 0)  # reaped without any create()/list() call
        assert wait_for(lambda: s.state == "ended")
    finally:
        m.close_all()
    assert m._janitor is None


def test_janitor_spares_sessions_with_clients_and_stops_on_close_all(tmp_path):
    now = [0.0]
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    fake = FakePtyBackend()
    m = TerminalManager(backend=fake, idle_seconds=10, clock=lambda: now[0], environ={"PATH": "/bin"},
                        janitor_interval=0.01)
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        s = m.create(proj, prof)
        m.subscribe(s.id, loop)
        now[0] += 1000
        time.sleep(0.15)
        assert fake.spawned[0].terminated == 0  # a connected client protects the session
        t = m._janitor
    finally:
        m.close_all()
        loop.close()
    assert t is not None and not t.is_alive()


def test_janitor_restarts_after_close_all(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    m = TerminalManager(backend=FakePtyBackend(), environ={"PATH": "/bin"}, janitor_interval=0.05)
    m.create(proj, prof)
    m.close_all()
    m.create(proj, prof)
    try:
        assert m._janitor is not None and m._janitor.is_alive()
        assert sum(t.name == "pty-janitor" and t.is_alive() for t in threading.enumerate()) >= 1
    finally:
        m.close_all()


# ------------------------------------------------------------------ Ctrl+C
def test_ctrl_c_forwarded_unmodified(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    proj = Project("p1", "p", str(d), time.time())
    prof = Profile(id="a", name="A", command=sys.executable)
    fake = FakePtyBackend(echo=False)
    m = TerminalManager(backend=fake, environ={"PATH": "/bin"})
    try:
        s = m.create(proj, prof)
        m.write(s.id, b"\x03")
        m.write(s.id, "\x03")
        m.write(s.id, b"a\x03b\x04\x1a")
        assert b"".join(fake.spawned[0].written) == b"\x03\x03a\x03b\x04\x1a"
        assert fake.spawned[0].terminated == 0 and s.state == "active"  # the manager does not interpret it
    finally:
        m.close_all()
