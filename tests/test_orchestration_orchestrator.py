"""Orchestrator behaviour with the FakeLauncher: plan, model choice, escalation, parallel limit, budget, cost."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from app.orchestration.launchers import FakeLauncher, InProcessModelLauncher, SessionLauncher
from app.orchestration.orchestrator import Orchestrator, plan
from app.orchestration.runs import Run
from tests.orch_helpers import M, cfg, five, make_registry, orch, project, three

TASK = "Corrigir o bug no parser"


def roles_models(launcher):
    return [(c["role"], c["model_id"]) for c in launcher.calls]


def test_launcher_protocol():
    assert isinstance(FakeLauncher(), SessionLauncher)
    assert isinstance(InProcessModelLauncher(None), SessionLauncher)


def test_plan_pipeline_deterministic():
    a, b = plan(TASK), plan(TASK)
    assert [(s.step_id, s.role, s.depends_on) for s in a] == [(s.step_id, s.role, s.depends_on) for s in b]
    assert [s.role for s in a] == ["researcher", "implementer", "reviewer"]
    assert all(TASK in s.text for s in a)
    assert a[2].depends_on == ["implementer"]
    multi = plan("- ler a\n- ler b\n- ler c")
    assert [s.step_id for s in multi][:3] == ["researcher-1", "researcher-2", "researcher-3"]
    assert multi[3].depends_on == ["researcher-1", "researcher-2", "researcher-3"]
    with pytest.raises(ValueError):
        plan("   ")


@pytest.mark.parametrize("preset,expected", [
    ("economic", {"researcher": "t1", "implementer": "t2", "reviewer": "t2"}),
    ("balanced", {"researcher": "t2", "implementer": "t3", "reviewer": "t2"}),
    ("max", {"researcher": "t3", "implementer": "t3", "reviewer": "t3"}),
])
def test_models_per_role_by_preset(tmp_path, preset, expected):
    o, fl = orch(tmp_path)
    s = o.run(TASK, preset, project(tmp_path))
    assert s["state"] == "done", s
    assert dict(roles_models(fl)) == expected
    run = Run.load(project(tmp_path), s["run_id"])
    for sid in ("researcher", "implementer", "reviewer"):
        assert run.read_result(sid)
    assert [st["state"] for st in s["steps"]] == ["done"] * 3


def test_five_tier_registry(tmp_path):
    o, fl = orch(tmp_path, registry=five(tmp_path))
    o.run(TASK, "economic", project(tmp_path))
    got = dict(roles_models(fl))
    assert got["researcher"] in ("t1", "t2") and got["implementer"] == "t3" and got["reviewer"] == "t3"


def test_class_without_model_falls_up_with_warning(tmp_path):
    reg = make_registry(tmp_path, M("l1", 1, provider="ollama", local=True), M("t2", 2, price=(1, 2)),
                        M("t3", 3, price=(5, 5)))
    fl = FakeLauncher(input_tokens=1, output_tokens=1)
    o = Orchestrator(fl, registry=reg, config=cfg(), available_providers={"anthropic"}, sync=True)
    s = o.run(TASK, "economic", project(tmp_path))
    assert s["state"] == "done"
    assert dict(roles_models(fl))["researcher"] == "t2"
    assert any("class_cheap_has_no_connected_model" in w for w in s["warnings"])
    assert s["steps"][0]["effective_class"] == "medium" and s["steps"][0]["class"] == "cheap"


def test_no_usable_model_fails_run(tmp_path):
    fl = FakeLauncher()
    o = Orchestrator(fl, registry=three(tmp_path), config=cfg(), available_providers=set(), sync=True)
    s = o.run(TASK, "balanced", project(tmp_path))
    assert s["state"] == "failed" and s["reason"].startswith("no_model_available")
    assert fl.calls == []


def test_unknown_preset_does_not_create_run(tmp_path):
    from app.orchestration.config import OrchestrationConfigError
    o, _ = orch(tmp_path)
    with pytest.raises(OrchestrationConfigError):
        o.submit(TASK, "turbo", project(tmp_path))
    assert not (project(tmp_path) / ".anamnesia").exists()


# ---- escalation
def test_escalates_one_class_after_two_failures(tmp_path):
    fl = FakeLauncher(behavior=lambda c: {"ok": c["model_id"] != "t1", "error": "boom"},
                      input_tokens=10, output_tokens=5)
    o, _ = orch(tmp_path, launcher=fl)
    s = o.run(TASK, "economic", project(tmp_path))
    assert s["state"] == "done"
    assert [m for r, m in roles_models(fl) if r == "researcher"] == ["t1", "t1", "t2"]
    st = s["steps"][0]
    assert st["escalated_from"] == "t1" and st["model_id"] == "t2" and len(st["attempts"]) == 3
    run = Run.load(project(tmp_path), s["run_id"])
    esc = [e for e in run.events() if e["type"] == "escalated"]
    assert len(esc) == 1 and esc[0]["from_model"] == "t1" and esc[0]["to_model"] == "t2"


def test_one_failure_does_not_escalate(tmp_path):
    n = {"t1": 0}

    def beh(c):
        if c["model_id"] == "t1":
            n["t1"] += 1
            return {"ok": n["t1"] > 1}
        return {}
    fl = FakeLauncher(behavior=beh, input_tokens=1, output_tokens=1)
    o, _ = orch(tmp_path, launcher=fl)
    s = o.run(TASK, "economic", project(tmp_path))
    assert s["state"] == "done" and [m for r, m in roles_models(fl) if r == "researcher"] == ["t1", "t1"]
    assert "escalated_from" not in s["steps"][0]


def test_escalation_exhausted_fails_run(tmp_path):
    fl = FakeLauncher(behavior=lambda c: {"ok": False, "error": "nope"})
    o, _ = orch(tmp_path, launcher=fl)
    s = o.run(TASK, "economic", project(tmp_path))
    assert s["state"] == "failed" and s["reason"].startswith("step_failed:researcher")
    # t1 x2, escalate once to t2 x2, then stop (only one escalation)
    assert [m for _, m in roles_models(fl)] == ["t1", "t1", "t2", "t2"]
    assert [st["state"] for st in s["steps"]] == ["failed", "pending", "pending"]


def test_top_class_failure_cannot_escalate(tmp_path):
    fl = FakeLauncher(behavior=lambda c: {"ok": False})
    o, _ = orch(tmp_path, launcher=fl)
    s = o.run(TASK, "max", project(tmp_path))
    assert s["state"] == "failed" and len(fl.calls) == 2


# ---- parallel limit
def test_parallel_limit_respected(tmp_path):
    fl = FakeLauncher(delay_s=0.1, input_tokens=1, output_tokens=1)
    o, _ = orch(tmp_path, launcher=fl, max_parallel_subagents=2)
    s = o.run("- a\n- b\n- c\n- d", "max", project(tmp_path))
    assert s["state"] == "done"
    assert fl.max_concurrent == 2


def test_parallel_default_three(tmp_path):
    fl = FakeLauncher(delay_s=0.1, input_tokens=1, output_tokens=1)
    o, _ = orch(tmp_path, launcher=fl)
    o.run("- a\n- b\n- c\n- d\n- e", "max", project(tmp_path))
    assert fl.max_concurrent == 3


def test_dependencies_respected(tmp_path):
    o, fl = orch(tmp_path)
    o.run("- a\n- b", "max", project(tmp_path))
    assert [c["role"] for c in fl.calls][-2:] == ["implementer", "reviewer"]
    impl = next(c for c in fl.calls if c["role"] == "implementer")
    assert "[fake researcher] done" in impl["text"]


def test_read_only_env_flag(tmp_path):
    o, fl = orch(tmp_path)
    o.run(TASK, "balanced", project(tmp_path))
    ro = {c["role"]: c["env"]["ANAMNESIA_READ_ONLY"] for c in fl.calls}
    assert ro == {"researcher": "1", "implementer": "0", "reviewer": "1"}


# ---- cost & budget
def test_cost_measured_only_with_verified_price(tmp_path):
    o, _ = orch(tmp_path)
    s = o.run(TASK, "economic", project(tmp_path))
    r, i, v = s["steps"]
    assert r["cost_status"] == "measured" and r["cost_usd"] == pytest.approx((100 * 1 + 50 * 2) / 1e6)
    assert i["cost_usd"] == pytest.approx((100 * 3 + 50 * 6) / 1e6)
    assert s["totals"]["cost_status"] == "measured"
    assert s["totals"]["cost_usd"] == pytest.approx(sum(x["cost_usd"] for x in s["steps"]))
    assert s["totals"]["input_tokens"] == 300 and s["totals"]["output_tokens"] == 150


def test_no_cost_estimate_when_price_unavailable(tmp_path):
    o, _ = orch(tmp_path, registry=three(tmp_path, price=False))
    s = o.run(TASK, "balanced", project(tmp_path))
    assert s["state"] == "done"
    for st in s["steps"]:
        assert st["cost_usd"] is None and st["cost_status"] == "unavailable"
        assert st["price_status"] == "unavailable"
        assert st["input_tokens"] == 100            # tokens are still reported when measured
    assert s["totals"]["cost_usd"] is None and s["totals"]["cost_status"] == "unavailable"


def test_no_cost_when_usage_not_reported(tmp_path):
    o, _ = orch(tmp_path, launcher=FakeLauncher())    # launcher reports tokens = None
    s = o.run(TASK, "balanced", project(tmp_path))
    assert all(st["cost_usd"] is None and st["input_tokens"] is None for st in s["steps"])
    assert s["totals"]["cost_usd"] is None


def test_local_model_cost_zero(tmp_path):
    reg = make_registry(tmp_path, M("l1", 1, provider="ollama", local=True),
                        M("l2", 2, provider="ollama", local=True), M("l3", 3, provider="ollama", local=True))
    o, _ = orch(tmp_path, registry=reg)
    s = o.run(TASK, "max", project(tmp_path))
    assert s["totals"]["cost_usd"] == 0.0 and s["steps"][0]["attempts"][0]["cost_status"] == "local_zero"


def test_budget_stops_run(tmp_path):
    o, fl = orch(tmp_path)
    s = o.run(TASK, "economic", project(tmp_path), budget_usd=0.0005)
    assert s["state"] == "failed" and s["reason"].startswith("budget_exceeded")
    assert [r for r, _ in roles_models(fl)] == ["researcher", "implementer"]   # reviewer never launched
    run = Run.load(project(tmp_path), s["run_id"])
    assert run.summary["state"] == "failed"


def test_budget_blocks_before_launch_when_it_cannot_fit(tmp_path):
    o, fl = orch(tmp_path)
    # researcher costs 0.0002; implementer would cost 0.0006 > remaining
    s = o.run(TASK, "economic", project(tmp_path), budget_usd=0.0007)
    assert s["state"] == "failed"
    assert s["reason"].startswith("budget_exhausted") or s["reason"].startswith("budget_exceeded")
    assert s["totals"]["cost_usd"] <= 0.0007 + 1e-9 or s["reason"].startswith("budget_exceeded")


def test_budget_ok_when_enough(tmp_path):
    o, _ = orch(tmp_path)
    s = o.run(TASK, "economic", project(tmp_path), budget_usd=1.0)
    assert s["state"] == "done" and s["budget_usd"] == 1.0


def test_budget_unenforceable_without_price(tmp_path):
    o, fl = orch(tmp_path, registry=three(tmp_path, price=False))
    s = o.run(TASK, "balanced", project(tmp_path), budget_usd=1.0)
    assert s["state"] == "failed" and s["reason"].startswith("budget_unenforceable")
    assert fl.calls == []


def test_budget_from_config_limit(tmp_path):
    o, _ = orch(tmp_path, budget_usd=0.0001)
    s = o.run(TASK, "economic", project(tmp_path))
    assert s["state"] == "failed" and s["budget_usd"] == 0.0001


# ---- cancel
def test_cancel_running_run(tmp_path):
    ev = threading.Event()
    fl = FakeLauncher(behavior=lambda c: {"block": ev}, input_tokens=1, output_tokens=1)
    o, _ = orch(tmp_path, launcher=fl, sync=False)
    rid = o.submit(TASK, "balanced", project(tmp_path))
    for _ in range(300):
        if fl.calls:
            break
        threading.Event().wait(0.01)
    assert o.cancel(rid) == "cancelling"
    ev.set()
    assert o.wait(rid, 10)
    s = o.get(rid).summary
    assert s["state"] == "cancelled" and s["reason"] == "cancelled_by_user"
    assert len(fl.calls) == 1 and fl.closed
    assert o.cancel(rid) == "cancelled"        # idempotent on terminal state


# ---- in-process launcher (stub adapter, no network)
def test_inprocess_launcher_runs_role_via_adapter(tmp_path):
    reg = three(tmp_path)
    seen = []

    class Ad:
        def generate(self, prompt, max_tokens=0, **kw):
            seen.append(prompt)
            return SimpleNamespace(answer="findings: x", error=None, input_tokens=7, output_tokens=3,
                                   latency_ms=12.0)
    ln = InProcessModelLauncher(reg, adapter_factory=lambda entry: Ad())
    o, _ = orch(tmp_path, registry=reg, launcher=ln)
    s = o.run(TASK, "economic", project(tmp_path))
    assert s["state"] == "done" and len(seen) == 3
    assert "READ-ONLY" in seen[0] and TASK in seen[0]
    assert s["steps"][0]["input_tokens"] == 7 and s["steps"][0]["latency_ms"] == 12.0


def test_inprocess_adapter_error_is_step_failure(tmp_path):
    reg = three(tmp_path)

    class Bad:
        def generate(self, prompt, max_tokens=0, **kw):
            raise RuntimeError("down")
    o, _ = orch(tmp_path, registry=reg, launcher=InProcessModelLauncher(reg, adapter_factory=lambda e: Bad()))
    s = o.run(TASK, "max", project(tmp_path))
    assert s["state"] == "failed" and "RuntimeError" in s["steps"][0]["attempts"][0]["error"]
