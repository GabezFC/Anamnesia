"""Onda 4d: ANA-169 rotulo de enforcement, 173 broker/denial, 174 diff gate, 176 policy engine, 182 handoff, 192 manifesto."""
from __future__ import annotations

import json
import subprocess

import pytest

from app.orchestration import diff_gate, enforcement, handoff
from app.orchestration.launchers import FakeLauncher, InProcessModelLauncher, TerminalLauncher
from app.orchestration.roles import PermissionDenied
from app.policy import engine as pe
from app.policy import tools_manifest as tm


@pytest.fixture()
def audit_file(tmp_path, monkeypatch):
    p = tmp_path / "policy_audit.jsonl"
    monkeypatch.setenv("ANAMNESIA_POLICY_AUDIT", str(p))
    pe._tails.clear()
    return p


# ------------------------------------------------------------ ANA-176 policy engine
def test_off_by_default_and_silent(audit_file, monkeypatch):
    monkeypatch.delenv("ANAMNESIA_POLICY", raising=False)
    d = pe.check("write", "/x/y.py", {"actor": "researcher"})
    assert d.allowed and d.mode == "off" and not audit_file.exists()


def test_default_deny_in_enforce(audit_file, monkeypatch, tmp_path):
    monkeypatch.setenv("ANAMNESIA_POLICY", "enforce")
    ctx = {"actor": "researcher", "cwd": str(tmp_path)}
    for action in ("write", "exec", "pay", "escalate"):
        with pytest.raises(pe.PolicyDenied):
            pe.require(action, "anything", ctx)
    assert pe.require("read", "a.md", ctx).allowed


def test_implementer_may_write_only_inside_cwd(audit_file, monkeypatch, tmp_path):
    monkeypatch.setenv("ANAMNESIA_POLICY", "enforce")
    ctx = {"actor": "implementer", "cwd": str(tmp_path)}
    assert pe.require("write", str(tmp_path / "a.py"), ctx).allowed
    with pytest.raises(pe.PolicyDenied):
        pe.require("write", str(tmp_path.parent / "out.py"), ctx)
    with pytest.raises(pe.PolicyDenied):          # deny beats allow
        pe.require("write", str(tmp_path / ".env"), ctx)
    with pytest.raises(pe.PolicyDenied):
        pe.require("write", str(tmp_path / ".git" / "config"), ctx)


def test_audit_mode_logs_but_never_raises(audit_file, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_POLICY", "audit")
    d = pe.require("pay", "model:x", {"actor": "researcher"})
    assert not d.allowed and d.mode == "audit"
    assert pe.read_audit()[0]["event"] == "policy_denied"


def test_audit_chain_detects_tampering(audit_file, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_POLICY", "audit")
    for i in range(4):
        pe.check("read", f"n{i}.md", {"actor": "a"})
    assert pe.verify_chain() == (True, 4)
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[1])
    rec["target"] = "forged"
    lines[1] = json.dumps(rec)
    audit_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert pe.verify_chain()[0] is False


def test_audit_records_no_payload(audit_file, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_POLICY", "audit")
    pe.check("exec", "agent:codex", {"actor": "orchestrator", "run_id": "r1", "prompt": "SEGREDO-123", "argv": ["x"]})
    assert "SEGREDO-123" not in audit_file.read_text(encoding="utf-8")


def test_bad_policy_is_rejected():
    with pytest.raises(pe.PolicyError):
        pe.parse_policy({"rules": [{"id": "a", "effect": "maybe", "action": "write"}]})
    with pytest.raises(pe.PolicyError):
        pe.parse_policy({"defaults": {"write": "allow2"}})


def test_shipped_policy_file_loads():
    p = pe.load_policy()
    assert p.source.endswith("policy.yaml") and p.defaults["write"] == "deny" and p.rules


def test_side_effect_coverage_is_documented_honestly():
    """Known side-effect points. `routed` ones have a guard today; the rest are LISTED, not hidden."""
    routed = {"model_calls": "ensure_paid_allowed (ANA-168 kill-switch)",
              "role_actions": "roles.check_action (via enforcement.enforce, opt-in ANAMNESIA_ENFORCE_ROLES)"}
    not_yet_through_policy_check = ["launchers.TerminalLauncher.launch", "git worktree creation",
                                    "mcp memory_save", "exec_audit launchers"]
    assert routed and not_yet_through_policy_check          # the list exists and is intentionally non-empty
    import app.orchestration.orchestrator as orch
    assert "app.policy" not in open(orch.__file__, encoding="utf-8").read()   # still not wired: do not pretend


# ------------------------------------------------------------ ANA-169 / 173
def test_enforcement_labels_are_honest():
    class Reg: pass
    assert enforcement.enforcement_level(InProcessModelLauncher(Reg(), adapter_factory=lambda e: None), "reviewer") == "hard"
    assert enforcement.enforcement_level(FakeLauncher(), "reviewer") == "best_effort"
    assert enforcement.enforcement_level(object.__new__(TerminalLauncher), "implementer") == "soft"
    assert all(enforcement.enforcement_level(FakeLauncher(), r) in enforcement.LEVELS
               for r in ("orchestrator", "researcher", "implementer", "reviewer"))


def test_readonly_argv_only_claims_hard_when_verified():
    c = enforcement.readonly_argv("claude", "reviewer")
    assert c["argv"] == ["--permission-mode", "plan"] and c["verified"] and c["level"] == "hard"
    x = enforcement.readonly_argv("codex", "researcher")
    assert x["verified"] is False and x["level"] == "best_effort"          # codex not installed here
    assert enforcement.readonly_argv("claude", "implementer")["argv"] == []
    assert enforcement.readonly_argv("nope", "reviewer")["level"] == "best_effort"


def test_reviewer_write_is_denied_and_audited(audit_file, tmp_path):
    with pytest.raises(PermissionDenied):
        enforcement.enforce("reviewer", "write_files", str(tmp_path / "x.py"), str(tmp_path), run_id="r1", step="s1")
    row = pe.read_audit()[-1]
    assert row["event"] == "policy_denied" and row["actor"] == "reviewer" and row["run_id"] == "r1"
    assert pe.verify_chain()[0]
    enforcement.enforce("reviewer", "run_tests")           # allowed: no raise
    with pytest.raises(PermissionDenied):                   # implementer outside cwd
        enforcement.enforce("implementer", "write_files", str(tmp_path.parent / "o.py"), str(tmp_path))


def test_summary_json_has_enforcement_per_step(tmp_path):
    from tests.orch_helpers import orch, project
    o, _ = orch(tmp_path, launcher=FakeLauncher(input_tokens=1, output_tokens=1), sync=True)
    rid = o.submit("Revisar o modulo de busca e propor correcao", "balanced", project(tmp_path))
    steps = o.get(rid).summary["steps"]
    assert steps and all(st["enforcement"] == "best_effort" for st in steps)
    on_disk = json.loads((o.get(rid).dir / "summary.json").read_text(encoding="utf-8"))
    assert all("enforcement" in st for st in on_disk["steps"])


# ------------------------------------------------------------ ANA-174 diff gate
def test_verify_diff_pure():
    ok, bad = diff_gate.verify_diff(["app/a.py", "tests/t.py"], ["app", "tests/*.py"])
    assert ok and bad == []
    ok, bad = diff_gate.verify_diff(["app/a.py", "../evil.py", "/etc/x", "C:/x.py", "docs/a.md", "app/../x"], ["app"])
    assert not ok and set(bad) == {"../evil.py", "/etc/x", "C:/x.py", "docs/a.md", "app/../x"}


def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "app").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / "app" / "a.py").write_text("x=1\n")
    (r / "docs" / "d.md").write_text("d\n")
    _git(r, "init", "-q")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "init")
    return r


def test_gate_accepts_in_scope_change(repo):
    (repo / "app" / "a.py").write_text("x=2\n")
    res = diff_gate.gate_worktree(repo, ["app"])
    assert res["ok"] and res["changed"] == ["app/a.py"] and not res["reverted"]
    assert (repo / "app" / "a.py").read_text() == "x=2\n"


def test_gate_reverts_out_of_scope_change(repo):
    (repo / "app" / "a.py").write_text("x=2\n")
    (repo / "docs" / "d.md").write_text("changed\n")
    (repo / "new_outside.txt").write_text("n\n")
    res = diff_gate.gate_worktree(repo, ["app"])
    assert not res["ok"] and set(res["violations"]) == {"docs/d.md", "new_outside.txt"} and res["reverted"]
    assert (repo / "docs" / "d.md").read_text() == "d\n" and not (repo / "new_outside.txt").exists()
    assert diff_gate.changed_paths(repo) == []


def test_gate_flag_default_off(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_DIFF_GATE", raising=False)
    assert diff_gate.diff_gate_enabled() is False


# ------------------------------------------------------------ ANA-182 handoff
def test_handoff_roundtrip_and_summary(tmp_path):
    doc = {"findings": ["F1"], "files_touched": ["app/a.py"], "open_questions": ["Q?"], "artifacts": ["out.md"], "confidence": 0.7}
    handoff.write(tmp_path, doc)
    got = handoff.read(tmp_path)
    assert got == doc
    txt = handoff.summarize_for_next(got, tmp_path)
    assert "F1" in txt and "app/a.py" in txt and "handoff.json" in txt


@pytest.mark.parametrize("bad", [[], {"findings": "x"}, {"findings": [1]}, {"x": 1}, {"confidence": 2},
                                 {"confidence": True}, {"findings": ["a"] * 51}, {"artifacts": ["a" * 501]}])
def test_handoff_rejects_invalid(bad):
    with pytest.raises(handoff.HandoffInvalid):
        handoff.validate(bad)


def test_handoff_confidence_is_never_invented(tmp_path):
    handoff.write(tmp_path, {"findings": ["a"]})
    assert handoff.read(tmp_path)["confidence"] is None


def test_handoff_corrupt_file_reads_as_none(tmp_path):
    (tmp_path / "handoff.json").write_text("{not json", encoding="utf-8")
    assert handoff.read(tmp_path) is None and handoff.read(tmp_path / "missing") is None


# ------------------------------------------------------------ ANA-192 manifest
def test_exposed_tools_equal_manifest():
    assert tm.declared_tools() == set(tm.MANIFEST)


def test_every_tool_is_classified():
    for name, m in tm.MANIFEST.items():
        assert m["scope"] in ("read", "write", "compute") and m["risk"] in ("low", "medium", "high") and m["enabled_by"]


def test_restricted_profile_is_read_only_subset():
    assert tm.allowed_for_profile("restricted") == ("memory_search",)
    assert all(tm.MANIFEST[t]["scope"] == "read" for t in tm.allowed_for_profile("readonly"))
    assert not tm.is_allowed("memory_save", "restricted") and tm.is_allowed("memory_save", "default")
    with pytest.raises(KeyError):
        tm.allowed_for_profile("nope")


def test_tool_use_log_has_no_arguments(audit_file):
    tm.log_use("memory_save", "default", True, run_id="r9")
    row = pe.read_audit()[0]
    assert row["event"] == "tool_use" and row["target"] == "tool:memory_save" and row["scope"] == "write"
    assert pe.verify_chain()[0]
