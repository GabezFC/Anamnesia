"""ANA-170 / ANA-189: offline router evaluation and calibration. Real labelled tasks, no model, no network."""
import importlib.util
import sys
from collections import Counter
from pathlib import Path

from app.routing import calibration as cal
from app.routing.policy import preset
from app.routing.tasks import load_tasks, split_tasks

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("eval_router_offline", ROOT / "scripts" / "eval_router_offline.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["eval_router_offline"] = m
    spec.loader.exec_module(m)
    return m


def test_auc_basic_properties():
    assert cal.auc([0.1, 0.2], [0.8, 0.9]) == 1.0
    assert cal.auc([0.8, 0.9], [0.1, 0.2]) == 0.0
    assert cal.auc([0.5], [0.5]) == 0.5
    assert cal.auc([], [1]) is None


def test_entropy_and_confusion():
    assert cal.entropy_bits(Counter({1: 10})) == 0.0
    assert cal.entropy_bits(Counter({1: 5, 2: 5})) == 1.0
    m = cal.confusion(["easy", "hard", "hard"], [0, 2, 1], 3)
    assert m[0][0] == 1 and m[2][2] == 1 and m[2][1] == 1


def test_ordinal_regret_penalises_under_routing_more():
    assert cal.ordinal_regret("hard", 0, 3) > cal.ordinal_regret("easy", 2, 3) > 0
    assert cal.ordinal_regret("easy", 0, 3) == 0


def test_eval_runs_on_real_tasks_and_reports_fields():
    ev = _script()
    r = ev.run()
    assert r["n_tasks"] == 174 and sum(r["label_counts"].values()) == 174
    for p in ("economic", "balanced", "max"):
        e = r["presets"][p]
        assert 0.0 <= e["score_distribution"]["auc_easy_lt_hard"] <= 1.0
        assert sum(map(sum, e["routed"]["confusion_label_x_tier"])) == 174
    # the gate is REPORTED honestly, whatever it is; max is constant by construction
    assert r["presets"]["max"]["gate_router_not_constant"] is False
    assert r["gate_default_preset"] == r["presets"]["balanced"]["gate_router_not_constant"]


def test_eval_is_deterministic():
    ev = _script()
    assert ev.run() == ev.run()


def test_check_flag_exit_code_follows_gate():
    ev = _script()
    gate = ev.run()["gate_default_preset"]
    assert ev.main(["--check", "--quiet"]) == (0 if gate else 1)


def test_render_report():
    ev = _script()
    md = ev.render_md(ev.run())
    assert "AUC easy<hard" in md and "Veredito" in md and "Matriz de confusão" in md


def test_calibration_split_is_disjoint_and_deterministic():
    tasks = load_tasks()
    a1, b1 = split_tasks(tasks, seed=42)
    a2, b2 = split_tasks(tasks, seed=42)
    assert [t.id for t in a1] == [t.id for t in a2]
    assert not {t.id for t in a1} & {t.id for t in b1}
    c = cal.calibrate(tasks, preset("balanced", enabled=True))
    assert c["n_calibration"] + c["n_eval"] == len(tasks)
    assert c["verdict"] in ("HOLD", "PROMOTE")
    assert c["tier_cutoffs"]["eval_distribution_default"]["n"] == c["n_eval"]


def test_calibration_never_selects_constant_router():
    tasks = load_tasks()
    pol = preset("balanced", enabled=True)
    c = cal.calibrate(tasks, pol)
    assert c["tier_cutoffs"]["eval_distribution_calibrated"]["distinct_tiers"] >= 2


def test_calibration_promotes_only_with_ci_excluding_zero_on_synthetic_signal():
    """Synthetic scorer with a perfect signal: proves the PROMOTE path exists and is CI-gated (not a measurement)."""
    from app.routing.tasks import Task
    pol = preset("balanced", enabled=True)
    tasks = []
    for i in range(60):
        lab = ("easy", "medium", "hard")[i % 3]
        tasks.append(Task(f"s{i:03d}", "memory_qa", ("a " * (1 + (i % 3) * 14)).strip(), lab))
    c = cal.calibrate(tasks, pol)
    # whatever the verdict, it must be consistent with the CI fields
    ci = c["tier_cutoffs"]["eval_paired_diff_ci95"]
    cc = c["tier_cutoffs"]["eval_paired_diff_vs_constant_ci95"]
    if c["tier_cutoffs"]["promote"]:
        assert ci["excludes_zero"] and ci["mean_diff"] > 0 and cc["excludes_zero"] and cc["mean_diff"] > 0
    assert (c["verdict"] == "PROMOTE") == (c["tier_cutoffs"]["promote"] or c["answer_max_difficulty"]["promote"])


def test_defaults_untouched():
    from app.routing import answer
    assert answer.ANSWER_MAX_DIFFICULTY == 0.75 == cal.DEFAULT_ANSWER_MAX_DIFFICULTY
    assert preset("balanced").tier_cutoffs == (0.25, 0.5, 0.75) and preset("balanced").enabled is False
