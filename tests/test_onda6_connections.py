"""Onda 6 - Connections: ANA-194 AgentCliLauncher, 195 perfil kind=agent, 196 runs orfaos, 197 CLI unica,
198 catalogo unico de agentes, 199 capability registry. Tudo offline (adapters/binarios falsos)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.adapters.models.providers import GenerationResult
from app.connections import agents as ag
from app.connections.agents import (AgentCatalogError, CapabilityError, check_consistency, check_role, get_agent,
                                    load_agents, missing_capabilities, pick_launcher)
from app.orchestration import delegate
from app.orchestration.launchers import AgentCliLauncher
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.runs import Run, recover_orphans
from tests.orch_helpers import cfg, project, three

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ ANA-198: single catalog, zero divergences
def test_catalog_loads_and_matches_profiles_and_connections():
    agents = load_agents()
    assert {a.id for a in agents} >= {"hermes", "claude-code", "codex", "opencode"}
    assert check_consistency() == []


def test_adding_an_agent_is_one_entry(tmp_path, monkeypatch):
    src = (ROOT / "config" / "agents.yaml").read_text("utf-8")
    extra = src + ("  - id: newagent\n    name: New Agent\n    command: newagent\n    supports: []\n"
                   "    validated_on: null\n    description: demo\n")
    p = tmp_path / "agents.yaml"
    p.write_text(extra, encoding="utf-8")
    monkeypatch.setattr(ag, "CATALOG_PATH", p)
    from app.connections.catalog import load_catalog
    from app.terminals.profiles import load_profiles
    assert "newagent" in load_profiles() and load_profiles()["newagent"].kind == "agent"
    assert "newagent" in {c.id for c in load_catalog()}
    assert check_consistency() == []        # derived views never diverge


def test_divergence_is_detected(monkeypatch):
    agents = load_agents()
    profiles = {p.id: p for p in __import__("app.terminals.profiles", fromlist=["x"]).load_profiles(derive=False).values()}
    bad = type(profiles["codex"])(**{**profiles["codex"].__dict__, "command": "other"}) \
        if hasattr(profiles["codex"], "__dict__") else None
    if bad is None:
        pytest.skip("Profile not constructible this way")
    profiles["codex"] = bad
    assert any("codex" in m and "command" in m for m in check_consistency(agents, profiles))


@pytest.mark.parametrize("mutate,needle", [
    ("status: sometimes", "status"),
    ("adapter: nope", "adapter"),
    ("supports: [fly]", "supports"),
    ("mcp_mode: wifi", "mcp_mode"),
])
def test_catalog_is_strict(tmp_path, mutate, needle):
    key = mutate.split(":")[0]
    base = {"status": "available", "adapter": "codex", "supports": "[]", "mcp_mode": "env"}
    base[key] = mutate.split(": ", 1)[1]
    txt = ("version: 1\nagents:\n  - id: a\n    name: A\n    command: a\n"
           + "".join(f"    {k}: {v}\n" for k, v in base.items()))
    p = tmp_path / "a.yaml"
    p.write_text(txt, encoding="utf-8")
    with pytest.raises(AgentCatalogError, match=needle):
        load_agents(p)


def test_duplicate_and_empty_catalog(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("version: 1\nagents:\n  - id: a\n    name: A\n    command: a\n  - id: a\n    name: B\n    command: b\n",
                 encoding="utf-8")
    with pytest.raises(AgentCatalogError, match="duplicate"):
        load_agents(p)
    p.write_text("version: 1\nagents: []\n", encoding="utf-8")
    with pytest.raises(AgentCatalogError):
        load_agents(p)


def test_headless_requires_adapter(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text("version: 1\nagents:\n  - id: a\n    name: A\n    command: a\n    supports: [headless]\n",
                 encoding="utf-8")
    with pytest.raises(AgentCatalogError, match="adapter"):
        load_agents(p)


# ------------------------------------------------------------------ ANA-199: capabilities
def test_unvalidated_agent_supports_nothing():
    oc = get_agent("opencode")
    assert not oc.validated and oc.effective_supports() == ()
    assert pick_launcher(oc) is None
    with pytest.raises(CapabilityError) as ei:
        check_role(oc, "implementer")
    assert ei.value.reason_code == "capability_missing:opencode:implementer:readonly_sandbox"


def test_implementer_refused_without_sandbox_but_allowed_with_it():
    assert missing_capabilities(get_agent("hermes"), "implementer") == ("readonly_sandbox",)
    assert missing_capabilities(get_agent("claude-code"), "implementer") == ()
    assert missing_capabilities(get_agent("hermes"), "researcher") == ()
    assert pick_launcher(get_agent("codex")) == "agent_cli"


def test_unknown_role_refused():
    with pytest.raises(CapabilityError):
        check_role(get_agent("codex"), "overlord")


def test_orchestrator_refuses_implementer_on_agent_without_sandbox(tmp_path):
    from app.orchestration.launchers import FakeLauncher
    fl = FakeLauncher(input_tokens=1, output_tokens=1)
    o = Orchestrator(fl, registry=three(tmp_path), config=cfg(), sync=True, profile_id="hermes")
    with pytest.raises(CapabilityError) as ei:
        o.submit("do it", "balanced", project(tmp_path))
    assert "implementer" in ei.value.reason_code
    assert fl.calls == [] and not (project(tmp_path) / ".anamnesia").exists()     # nothing launched, nothing written


def test_orchestrator_accepts_sandboxed_agent(tmp_path):
    from app.orchestration.launchers import FakeLauncher
    o = Orchestrator(FakeLauncher(input_tokens=1, output_tokens=1), registry=three(tmp_path), config=cfg(), sync=True,
                     profile_id="claude-code")
    rid = o.submit("do it", "balanced", project(tmp_path))
    assert o.get(rid).state == "done"


def test_non_agent_profile_not_judged_by_capabilities(tmp_path):
    from app.orchestration.launchers import FakeLauncher
    o = Orchestrator(FakeLauncher(input_tokens=1, output_tokens=1), registry=three(tmp_path), config=cfg(), sync=True,
                     profile_id="shell")
    assert o.get(o.submit("x", "balanced", project(tmp_path))).state == "done"


# ------------------------------------------------------------------ ANA-194: AgentCliLauncher
class FakeAdapter:
    def __init__(self, result=None, boom=None):
        self.result, self.boom, self.calls = result, boom, []

    def generate(self, prompt, model=None, **kw):
        self.calls.append({"prompt": prompt, "model": model, **kw})
        if self.boom:
            raise self.boom
        return self.result or GenerationResult("answer text", 111, 22, 33.0, "x", "m")


def _launch(tmp_path, adapter, profile="claude-code", registry=None, model_id="t1", **kw):
    fa = adapter
    lau = AgentCliLauncher(registry=registry, adapter_factory=lambda spec: fa, **kw)
    sdir = tmp_path / "step"
    sdir.mkdir(exist_ok=True)
    env = {"ANAMNESIA_STEP_DIR": str(sdir), "ANAMNESIA_MODEL_ID": model_id}
    sid = lau.launch(None, profile, env, str(tmp_path))
    return lau, sid, sdir


def test_agent_launcher_writes_contract_with_reported_usage(tmp_path):
    fa = FakeAdapter()
    lau, sid, sdir = _launch(tmp_path, fa, timeout_s=77)
    assert lau.is_alive(sid)
    lau.send(sid, "hello")
    st = json.loads((sdir / "status.json").read_text("utf-8"))
    assert st == {"ok": True, "error": None, "input_tokens": 111, "output_tokens": 22, "latency_ms": 33.0}
    assert (sdir / "result.md").read_text("utf-8") == "answer text"
    assert fa.calls[0]["timeout"] == 77 and fa.calls[0]["prompt"] == "hello"
    lau.close(sid)
    assert not lau.is_alive(sid)


def test_agent_launcher_never_invents_usage(tmp_path):
    fa = FakeAdapter(GenerationResult("ok", None, None, 5.0, "x", "m"))
    lau, sid, sdir = _launch(tmp_path, fa)
    lau.send(sid, "q")
    st = json.loads((sdir / "status.json").read_text("utf-8"))
    assert st["ok"] and st["input_tokens"] is None and st["output_tokens"] is None


@pytest.mark.parametrize("res,boom,needle", [
    (GenerationResult(None, None, None, 1.0, "x", "m", error="timeout"), None, "timeout"),
    (GenerationResult("  ", 1, 1, 1.0, "x", "m"), None, "empty"),
    (None, RuntimeError("kaput"), "RuntimeError"),
])
def test_agent_launcher_failures_become_failed_step(tmp_path, res, boom, needle):
    lau, sid, sdir = _launch(tmp_path, FakeAdapter(res, boom))
    lau.send(sid, "q")
    st = json.loads((sdir / "status.json").read_text("utf-8"))
    assert st["ok"] is False and needle in st["error"] and not (sdir / "result.md").exists()


@pytest.mark.parametrize("profile,needle", [
    ("nope", "agent_unknown"), ("opencode", "agent_not_headless"), (None, "agent_unknown"), ("shell", "agent_unknown"),
])
def test_agent_launcher_refuses_non_headless_profiles(tmp_path, profile, needle):
    lau = AgentCliLauncher(adapter_factory=lambda s: FakeAdapter())
    with pytest.raises(ValueError, match=needle):
        lau.launch(None, profile, {}, str(tmp_path))


def test_agent_launcher_model_only_for_matching_provider(tmp_path):
    reg = three(tmp_path)            # provider anthropic, model m-t1
    fa = FakeAdapter()
    lau, sid, _ = _launch(tmp_path, fa, "claude-code", registry=reg)
    lau.send(sid, "q")
    assert fa.calls[0]["model"] == "m-t1"
    fa2 = FakeAdapter()
    lau2, sid2, _ = _launch(tmp_path, fa2, "codex", registry=reg)     # codex = openai: do not pass an anthropic model
    lau2.send(sid2, "q")
    assert fa2.calls[0]["model"] is None


def test_agent_launcher_end_to_end_in_orchestrator(tmp_path):
    fa = FakeAdapter()
    lau = AgentCliLauncher(registry=three(tmp_path), adapter_factory=lambda s: fa)
    o = Orchestrator(lau, registry=three(tmp_path), config=cfg(), sync=True, profile_id="claude-code")
    rid = o.submit("do it", "balanced", project(tmp_path))
    s = o.get(rid).summary
    assert s["state"] == "done"
    assert s["totals"]["input_tokens"] == 111 * 3 and s["totals"]["cost_status"] == "measured"
    assert len(fa.calls) == 3


def test_real_adapter_is_built_lazily_for_known_adapter():
    lau = AgentCliLauncher()
    spec = get_agent("claude-code")
    assert type(lau._make(spec)).__name__ == "ClaudeCodeAdapter"      # constructing does not run any binary


# ------------------------------------------------------------------ ANA-195: delegate profile validation
@pytest.fixture()
def clean_delegate(monkeypatch):
    monkeypatch.setattr(delegate, "_term_orch", None)
    monkeypatch.delenv("ANAMNESIA_DELEGATE_PROFILE", raising=False)
    yield


@pytest.mark.parametrize("mode", ["terminal", "agent_cli"])
def test_delegate_refuses_shell_profile(clean_delegate, monkeypatch, mode):
    monkeypatch.setenv("ANAMNESIA_DELEGATE_LAUNCHER", mode)
    with pytest.raises(delegate.DelegateError) as ei:
        delegate.get_orchestrator()            # default profile is `shell`
    assert ei.value.reason_code == "profile_not_agent"
    monkeypatch.setenv("ANAMNESIA_DELEGATE_PROFILE", "ghost")
    with pytest.raises(delegate.DelegateError) as ei:
        delegate.get_orchestrator()
    assert ei.value.reason_code == "profile_unknown"


def test_delegate_accepts_agent_profile_and_rebuilds_on_change(clean_delegate, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_DELEGATE_LAUNCHER", "agent_cli")
    monkeypatch.setenv("ANAMNESIA_DELEGATE_PROFILE", "claude-code")
    a = delegate.get_orchestrator()
    assert type(a.launcher).__name__ == "AgentCliLauncher" and a.profile_id == "claude-code"
    assert delegate.get_orchestrator() is a
    monkeypatch.setenv("ANAMNESIA_DELEGATE_PROFILE", "codex")
    assert delegate.get_orchestrator().profile_id == "codex"
    monkeypatch.setenv("ANAMNESIA_DELEGATE_PROFILE", "shell")
    with pytest.raises(delegate.DelegateError):          # a bad env never reuses the cached orchestrator
        delegate.get_orchestrator()


def test_search_reports_machine_readable_refusal(clean_delegate, monkeypatch, tmp_path):
    import app.routing.answer as answer
    monkeypatch.setenv("ANAMNESIA_DELEGATE", "1")
    monkeypatch.setenv("ANAMNESIA_DELEGATE_LAUNCHER", "terminal")
    monkeypatch.setenv("MG_PROJECT_PATH", str(tmp_path))
    res = type("R", (), {"query": "q", "metrics": {}})()
    extras = answer._delegate(res, {})
    assert extras["fallback_reason"] == "delegate_error:profile_not_agent"


# ------------------------------------------------------------------ ANA-196: orphaned runs
def _mk_run(tmp_path, state):
    r = Run.create(project(tmp_path), "t", "balanced")
    r.summary["steps"] = [{"step_id": "researcher", "state": "running"}, {"step_id": "reviewer", "state": "pending"}]
    r.write_summary()
    if state != "planned":
        r.transition("running")
        if state in ("done", "failed"):
            r.transition(state, "x")
    return r


def test_running_and_planned_runs_without_thread_become_failed_orphaned(tmp_path):
    r1, r2, r3 = (_mk_run(tmp_path, s) for s in ("running", "planned", "done"))
    got = recover_orphans(project(tmp_path))
    assert sorted(got) == sorted([r1.run_id, r2.run_id])
    for rid, want in ((r1.run_id, "failed"), (r2.run_id, "failed"), (r3.run_id, "done")):
        s = Run.load(project(tmp_path), rid).summary
        assert s["state"] == want
    s1 = Run.load(project(tmp_path), r1.run_id).summary
    assert s1["reason"] == "orphaned" and {st["state"] for st in s1["steps"]} == {"failed"}
    assert any(e.get("new") == "failed" and e.get("reason") == "orphaned" for e in Run.load(project(tmp_path), r1.run_id).events())
    assert recover_orphans(project(tmp_path)) == []                  # idempotent
    assert recover_orphans(tmp_path / "does-not-exist") == []


def test_live_runs_are_spared(tmp_path):
    r = _mk_run(tmp_path, "running")
    assert recover_orphans(project(tmp_path), live_run_ids={r.run_id}) == []
    assert Run.load(project(tmp_path), r.run_id).state == "running"


def test_orchestrator_recovers_once_per_project_on_list_and_submit(tmp_path):
    from app.orchestration.launchers import FakeLauncher
    stale = _mk_run(tmp_path, "running")
    o = Orchestrator(FakeLauncher(input_tokens=1, output_tokens=1), registry=three(tmp_path), config=cfg(), sync=True)
    runs = {s["run_id"]: s for s in o.list(project(tmp_path))}
    assert runs[stale.run_id]["state"] == "failed" and runs[stale.run_id]["reason"] == "orphaned"
    new = o.submit("x", "balanced", project(tmp_path))                # a live run in the same process is never touched
    assert o.get(new).state == "done"
    assert not [s for s in o.list(project(tmp_path)) if s["state"] == "running"]


def test_lifespan_recovers_registered_projects(tmp_path, monkeypatch):
    from app.api import workspace
    stale = _mk_run(tmp_path, "running")
    fake = type("Reg", (), {"list": lambda self: [type("P", (), {"id": "p", "path": str(project(tmp_path))})()]})()
    monkeypatch.setattr(workspace, "get_registry", lambda: fake)
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()):
        pass
    assert Run.load(project(tmp_path), stale.run_id).state == "failed"


# ------------------------------------------------------------------ ANA-197: unified CLI
def test_cli_exposes_unified_commands():
    from anamnesia.cli import PASSTHROUGH, build_parser
    p = build_parser()
    for name in ("version", "doctor", "start", "mcp", *PASSTHROUGH):
        assert p.parse_args([name]).cmd == name
    assert {"search", "index", "memory-audit", "vault-lint"} <= set(PASSTHROUGH)


def test_cli_passthrough_delegates_and_keeps_exit_codes(monkeypatch):
    import app.cli.main as legacy
    from anamnesia import cli
    seen = []

    def fake_main(argv):
        seen.append(argv)
        sys.exit(3)

    monkeypatch.setattr(legacy, "main", fake_main)
    assert cli.main(["vault-lint", "--json", "--vault", "x"]) == 3
    assert seen == [["vault-lint", "--json", "--vault", "x"]]
    monkeypatch.setattr(legacy, "main", lambda argv: sys.exit("boom message"))
    assert cli.main(["index"]) == 1
    monkeypatch.setattr(legacy, "main", lambda argv: None)
    assert cli.main(["info"]) == 0


def test_cli_mcp_subcommand_runs_server_main(monkeypatch):
    import app.mcp.server as srv
    from anamnesia import cli
    called = []
    monkeypatch.setattr(srv, "main", lambda: called.append(1))
    assert cli.main(["mcp"]) == 0 and called == [1]


def test_pyproject_declares_both_scripts():
    txt = (ROOT / "pyproject.toml").read_text("utf-8")
    assert 'anamnesia = "anamnesia.cli:main"' in txt and 'anamnesia-mcp = "app.mcp.server:main"' in txt


def test_quickstart_uses_only_anamnesia_command():
    q = (ROOT / "docs" / "guides" / "QUICKSTART.md").read_text("utf-8")
    assert "anamnesia-mcp" in q and "anamnesia search" in q
