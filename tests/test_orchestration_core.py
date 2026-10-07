"""Config, class->tier mapping, roles, run directory (traversal) and state machine."""
from __future__ import annotations

import json

import pytest

from app.orchestration.config import OrchestrationConfigError, class_tiers, load_config, parse_config
from app.orchestration.roles import PermissionDenied, check_action, contract
from app.orchestration.runs import InvalidTransition, Run, RunError, list_runs, safe_join
from app.routing.registry import _parse_yaml
from tests.orch_helpers import cfg, five, three


def test_default_config_loads():
    c = load_config()
    assert c.class_order == ("cheap", "medium", "strong")
    assert set(c.presets) == {"economic", "balanced", "max"}
    assert c.presets["economic"].roles == {"orchestrator": "strong", "researcher": "cheap",
                                           "implementer": "medium", "reviewer": "medium"}
    assert c.presets["balanced"].roles["implementer"] == "strong"
    assert set(c.presets["max"].roles.values()) == {"strong"}
    assert c.limits.max_parallel_subagents == 3 and c.limits.budget_usd is None
    assert c.limits.escalate_on_failures == 2


def test_class_to_tier_three_tiers(tmp_path):
    m = class_tiers(three(tmp_path).tiers(), cfg())
    assert m == {"cheap": [1], "medium": [2], "strong": [3]}


def test_class_to_tier_five_tiers(tmp_path):
    m = class_tiers(five(tmp_path).tiers(), cfg())
    assert m == {"cheap": [1, 2], "medium": [3], "strong": [4, 5]}


def test_class_to_tier_one_and_two_tiers():
    assert class_tiers([7], cfg()) == {"cheap": [7], "medium": [7], "strong": [7]}
    m = class_tiers([1, 9], cfg())
    assert m["cheap"] == [1] and m["strong"] == [9] and m["medium"] == []


def _doc():
    import pathlib
    return _parse_yaml((pathlib.Path(__file__).resolve().parents[1] / "config" / "orchestration.yaml")
                       .read_text("utf-8"))


@pytest.mark.parametrize("mutate", [
    lambda d: d["presets"]["economic"]["roles"].pop("reviewer"),
    lambda d: d["presets"]["economic"]["roles"].update(reviewer="godlike"),
    lambda d: d["presets"]["economic"].update(routing_preset="nope"),
    lambda d: d["limits"].update(max_parallel_subagents=0),
    lambda d: d["limits"].update(budget_usd=-1),
    lambda d: d["classes"]["medium"].update(rank_min=0.2),   # overlaps cheap
    lambda d: d["classes"].pop("strong"),
])
def test_config_validation_rejects(mutate):
    d = _doc()
    mutate(d)
    with pytest.raises(OrchestrationConfigError):
        parse_config(d)


def test_unknown_preset():
    with pytest.raises(OrchestrationConfigError):
        cfg().preset("turbo")


# ---- roles
def test_read_only_roles():
    for r in ("researcher", "reviewer"):
        assert contract(r).read_only
        with pytest.raises(PermissionDenied):
            check_action(r, "write_files", "a.txt", "/tmp")
    assert not contract("implementer").read_only
    check_action("reviewer", "run_tests")
    with pytest.raises(PermissionDenied):
        check_action("researcher", "run_tests")
    with pytest.raises(PermissionDenied):
        check_action("researcher", "format_disk")
    with pytest.raises(PermissionDenied):
        check_action("janitor", "read_files")


def test_implementer_writes_only_inside_cwd(tmp_path):
    cwd = tmp_path / "p"
    cwd.mkdir()
    check_action("implementer", "write_files", "src/a.py", cwd)
    check_action("implementer", "write_files", cwd / "b.py", cwd)
    with pytest.raises(PermissionDenied):
        check_action("implementer", "write_files", "../outside.py", cwd)
    with pytest.raises(PermissionDenied):
        check_action("implementer", "write_files", tmp_path / "other.py", cwd)
    with pytest.raises(PermissionDenied):
        check_action("implementer", "write_files", None, cwd)


# ---- run dir
def test_run_dir_created_with_files(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    r = Run.create(p, "do the thing", "balanced")
    assert r.dir == (p / ".anamnesia" / "runs" / r.run_id).resolve()
    assert (r.dir / "task.md").read_text(encoding="utf-8").strip() == "do the thing"
    assert json.loads((r.dir / "summary.json").read_text())["state"] == "planned"
    assert (r.dir / "events.jsonl").is_file()
    r.result_path("researcher").write_text("x", encoding="utf-8")
    assert Run.load(p, r.run_id).read_result("researcher") == "x"
    assert [s["run_id"] for s in list_runs(p)] == [r.run_id]


@pytest.mark.parametrize("bad", ["../x", "..", "a/b", "a\\b", "/abs", "C:\\x", "", ".", "x\x00y"])
def test_safe_join_rejects(tmp_path, bad):
    with pytest.raises(RunError):
        safe_join(tmp_path, bad)


@pytest.mark.parametrize("rid", ["../evil", "..", "a/b", "", "x" * 100, "-bad", "a b"])
def test_run_id_traversal_rejected(tmp_path, rid):
    with pytest.raises(RunError):
        Run.create(tmp_path, "t", "balanced", run_id=rid)
    with pytest.raises(RunError):
        Run.load(tmp_path, rid)
    assert not (tmp_path.parent / "evil").exists()


def test_step_id_traversal_rejected(tmp_path):
    r = Run.create(tmp_path, "t", "balanced")
    for bad in ("../x", "a/b", "..", "R"):
        with pytest.raises(RunError):
            r.step_dir(bad)


def test_missing_project_rejected(tmp_path):
    with pytest.raises(RunError):
        Run.create(tmp_path / "nope", "t", "balanced")


# ---- state machine
def test_state_machine(tmp_path):
    r = Run.create(tmp_path, "t", "balanced")
    assert r.state == "planned"
    with pytest.raises(InvalidTransition):
        r.transition("done")
    r.transition("running")
    r.transition("done")
    for s in ("running", "failed", "cancelled", "planned"):
        with pytest.raises(InvalidTransition):
            r.transition(s)
    types = [e["type"] for e in r.events()]
    assert types[0] == "created" and types.count("state") == 2


@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
def test_state_machine_other_terminals(tmp_path, terminal):
    r = Run.create(tmp_path, "t", "balanced")
    r.transition("running")
    r.transition(terminal, "why")
    assert r.summary["reason"] == "why"
    with pytest.raises(InvalidTransition):
        r.transition("done")
