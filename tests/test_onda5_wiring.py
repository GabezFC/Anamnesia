"""Onda 5: liga ao caminho de execucao as pecas PARCIAIS da Onda 4d (ANA-173/174/176/182/192), sempre opt-in.
Offline: git local temporario, FakeLauncher, sem rede."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestration import diff_gate, handoff
from app.orchestration.launchers import FakeLauncher, TerminalLauncher
from app.orchestration.orchestrator import Orchestrator
from app.policy import engine as pe
from app.policy import tools_manifest as tm
from tests.orch_helpers import cfg, three

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ("ANAMNESIA_ENFORCE_ROLES", "ANAMNESIA_DIFF_GATE", "ANAMNESIA_DIFF_GATE_SCOPE", "ANAMNESIA_POLICY",
         "ANAMNESIA_HANDOFF", "ANAMNESIA_TOOL_PROFILE")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for f in FLAGS:
        monkeypatch.delenv(f, raising=False)
    monkeypatch.setenv("ANAMNESIA_POLICY_AUDIT", str(tmp_path / "audit.jsonl"))
    pe._tails.clear()


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True,
                   capture_output=True)


def plain(tmp_path, name="proj"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo(tmp_path, name="proj"):
    d = plain(tmp_path, name)
    git(d, "init", "-q")
    (d / "src").mkdir()
    (d / "src" / "a.py").write_text("x = 1\n")
    (d / "README.md").write_text("hi\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")
    return d


def run_orch(tmp_path, d, behavior, **kw):
    fl = FakeLauncher(behavior, input_tokens=1, output_tokens=1)
    o = Orchestrator(fl, registry=three(tmp_path), config=cfg(), sync=True, **kw)
    rid = o.submit("do it", "balanced", d)
    return o.get(rid), fl


def writer(d, rel="README.md", roles=("implementer",)):
    def beh(call):
        if call["role"] in roles:
            (d / rel).write_text("tampered\n")
        return {}
    return beh


# ---------------------------------------------------------------- default OFF: nothing changes
def test_flags_off_by_default_no_gate_no_audit(tmp_path):
    d = repo(tmp_path)
    run, _ = run_orch(tmp_path, d, writer(d, roles=("researcher", "implementer", "reviewer")))
    assert run.state == "done"
    assert (d / "README.md").read_text() == "tampered\n"          # nothing reverted
    assert not (tmp_path / "audit.jsonl").exists()
    assert run.summary["warnings"] == []


# ---------------------------------------------------------------- ANA-173: read-only roles
def test_enforce_roles_flags_and_reverts_write_by_researcher(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ENFORCE_ROLES", "1")
    d = repo(tmp_path)
    run, _ = run_orch(tmp_path, d, writer(d, roles=("researcher",)))
    assert run.state == "failed"
    assert (d / "README.md").read_text() == "hi\n"                 # reverted
    assert "role_violation:write_in_read_only_role" in json.dumps(run.summary["steps"])
    assert any(e["type"] == "role_violation" for e in run.events())
    rec = pe.read_audit()
    assert rec and rec[0]["event"] == "policy_denied" and rec[0]["rule"] == "role_contract"
    assert pe.verify_chain()[0]


def test_enforce_roles_does_not_judge_implementer_nor_preexisting_dirt(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ENFORCE_ROLES", "1")
    d = repo(tmp_path)
    (d / "mine.txt").write_text("user work\n")                     # untracked, before the run
    run, _ = run_orch(tmp_path, d, writer(d, rel="src/a.py"))
    assert run.state == "done"
    assert (d / "mine.txt").exists()


def test_enforce_roles_skips_gate_outside_git(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ENFORCE_ROLES", "1")
    d = plain(tmp_path)
    run, _ = run_orch(tmp_path, d, None)
    assert run.state == "done"
    assert any(w.startswith("readonly_gate_skipped") for w in run.summary["warnings"])


# ---------------------------------------------------------------- ANA-174: diff gate
def test_diff_gate_reverts_out_of_scope_implementer(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE", "1")
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE_SCOPE", "src/")
    d = repo(tmp_path)
    run, _ = run_orch(tmp_path, d, writer(d, rel="README.md"))
    assert run.state == "failed"
    assert (d / "README.md").read_text() == "hi\n"
    assert "diff_gate_violation" in json.dumps(run.summary["steps"])
    assert pe.read_audit()[0]["rule"] == "diff_gate"


def test_diff_gate_allows_in_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE", "1")
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE_SCOPE", "src/")
    d = repo(tmp_path)
    run, _ = run_orch(tmp_path, d, writer(d, rel="src/a.py"))
    assert run.state == "done" and (d / "src" / "a.py").read_text() == "tampered\n"


def test_diff_gate_removes_untracked_violation(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE", "1")
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE_SCOPE", "src/")
    d = repo(tmp_path)
    run, _ = run_orch(tmp_path, d, writer(d, rel="evil.sh"))
    assert run.state == "failed" and not (d / "evil.sh").exists()


def test_diff_gate_without_scope_is_skipped_with_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DIFF_GATE", "1")
    d = repo(tmp_path)
    run, _ = run_orch(tmp_path, d, writer(d))
    assert run.state == "done" and "diff_gate_skipped:no_scope" in run.summary["warnings"]


def test_gate_since_never_touches_baseline(tmp_path):
    d = repo(tmp_path)
    (d / "README.md").write_text("user edit\n")
    base = diff_gate.snapshot(d)
    (d / "new.txt").write_text("x")
    res = diff_gate.gate_since(d, ["src/"], base)
    assert res["violations"] == ["new.txt"] and res["reverted"]
    assert (d / "README.md").read_text() == "user edit\n" and not (d / "new.txt").exists()


# ---------------------------------------------------------------- ANA-176: policy at the launch point
def test_policy_enforce_allows_orchestrator(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_POLICY", "enforce")
    run, fl = run_orch(tmp_path, plain(tmp_path), None)
    assert run.state == "done" and fl.calls
    assert all(r["event"] != "policy_denied" for r in pe.read_audit())


DENY_ALL = {"version": 1, "defaults": {"read": "allow", "write": "deny", "exec": "deny", "pay": "deny",
                                       "escalate": "deny"}, "rules": []}


def test_policy_enforce_denies_launch_without_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_POLICY", "enforce")
    monkeypatch.setattr(pe, "load_policy", lambda path=None: pe.parse_policy(DENY_ALL))
    run, fl = run_orch(tmp_path, plain(tmp_path), None)
    assert run.state == "failed" and fl.calls == []                 # nothing launched
    assert "PolicyDenied" in json.dumps(run.summary["steps"])


def test_policy_audit_mode_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_POLICY", "audit")
    monkeypatch.setattr(pe, "load_policy", lambda path=None: pe.parse_policy(DENY_ALL))
    run, _ = run_orch(tmp_path, plain(tmp_path), None)
    assert run.state == "done"
    assert any(r["event"] == "policy_denied" for r in pe.read_audit())


# ---------------------------------------------------------------- ANA-182: handoff injected into next prompt
def _handoff_behavior(call):
    if call["role"] == "researcher":
        handoff.write(call["env"]["ANAMNESIA_STEP_DIR"], {"findings": ["FINDING-XYZ"], "confidence": 0.5})
    return {}


def test_handoff_not_injected_when_off(tmp_path):
    _, fl = run_orch(tmp_path, plain(tmp_path), _handoff_behavior)
    assert all("FINDING-XYZ" not in c["text"] and "handoff.json" not in c["text"] for c in fl.calls)


def test_handoff_injected_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HANDOFF", "1")
    _, fl = run_orch(tmp_path, plain(tmp_path), _handoff_behavior)
    impl = [c for c in fl.calls if c["role"] == "implementer"][0]
    assert "FINDING-XYZ" in impl["text"] and "confidence: 0.5" in impl["text"]
    assert "handoff.json" in [c for c in fl.calls if c["role"] == "researcher"][0]["text"]


def test_invalid_handoff_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HANDOFF", "1")

    def beh(call):
        if call["role"] == "researcher":
            (Path(call["env"]["ANAMNESIA_STEP_DIR"]) / "handoff.json").write_text("{bad")
        return {}
    run, _ = run_orch(tmp_path, plain(tmp_path), beh)
    assert run.state == "done"


# ---------------------------------------------------------------- ANA-173 PTY: verified read-only switch only
def _harden(profile, ro="1", role="researcher"):
    return TerminalLauncher._harden(profile, {"ANAMNESIA_READ_ONLY": ro, "ANAMNESIA_ROLE": role})


def test_pty_harden_off_by_default():
    from app.terminals.profiles import load_profiles
    p = load_profiles()["claude-code"]
    assert _harden(p) is p


def test_pty_harden_adds_verified_flag_only_for_read_only_role(monkeypatch):
    from app.terminals.profiles import load_profiles
    monkeypatch.setenv("ANAMNESIA_ENFORCE_ROLES", "1")
    profs = load_profiles()
    h = _harden(profs["claude-code"])
    assert h.args[-2:] == ("--permission-mode", "plan") and h.id == "claude-code"
    assert "plan" not in profs["claude-code"].args                  # original untouched
    assert _harden(profs["claude-code"], ro="0", role="implementer") is profs["claude-code"]
    assert _harden(profs["codex"]) is profs["codex"]                # unverified => unchanged (stays soft)


# ---------------------------------------------------------------- ANA-192: profile filters the live server
def _tools(profile):
    env = {k: v for k, v in os.environ.items() if k != "ANAMNESIA_TOOL_PROFILE"}
    env.update(MG_MCP_SAVE="1", MG_MCP_TOOLSET="full")
    if profile:
        env["ANAMNESIA_TOOL_PROFILE"] = profile
    code = "from app.mcp import server;print(sorted(t.name for t in server.server._tool_manager.list_tools()))"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120,
                         cwd=str(ROOT))
    assert out.returncode == 0, out.stderr[-500:]
    return set(json.loads(out.stdout.strip().splitlines()[-1].replace("'", '"')))


@pytest.mark.parametrize("profile,expected", [
    ("restricted", {"memory_search"}),
    ("readonly", {"memory_search", "memory_search_baseline", "memory_search_graphify", "memory_search_graphify_jev",
                  "memory_get_run", "memory_stats"}),
    ("bogus", {"memory_search"}),                                   # unknown => fail closed
    ("", set(tm.MANIFEST)),                                          # unset => untouched (rollback)
])
def test_mcp_server_filtered_by_profile(profile, expected):
    assert _tools(profile) == expected
