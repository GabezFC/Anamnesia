"""ANA-190: principled router revision (ungrounded feature, train-only fit, held-out report). Offline."""
import importlib.util
import sys
from pathlib import Path

from app.routing import calibration as cal
from app.routing.policy import preset
from app.routing.router import difficulty_features, ungrounded_ids

ROOT = Path(__file__).resolve().parents[1]


def _rev():
    spec = importlib.util.spec_from_file_location("revise_router", ROOT / "scripts" / "revise_router.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["revise_router"] = m
    spec.loader.exec_module(m)
    return m


def test_ungrounded_feature_is_opt_in_and_query_only():
    pol = preset("balanced", enabled=True)
    assert "ungrounded" not in difficulty_features("Qual a porta do Postgres?", 0, pol)
    vocab = frozenset({"porta", "postgres"})
    assert ungrounded_ids("Qual a porta do Postgres?", vocab) == []
    assert "quibblenaut" in ungrounded_ids("Qual foi a decisao sobre o protocolo Quibblenaut 9.9?", vocab)
    f = difficulty_features("Qual foi a decisao sobre o protocolo Quibblenaut 9.9?", 0, pol, vocab)
    assert f["ungrounded"] == 1.0
    # file paths are input, not the ask
    assert ungrounded_ids("Nota 10-Trabalho/planejamento-trimestral-052.md: x", vocab) == []


def test_default_policy_unchanged_and_off():
    p = preset("balanced")
    assert p.enabled is False and p.tier_cutoffs == (0.25, 0.5, 0.75) and p.weights["ungrounded"] == 0.0


def test_bootstrap_ci_is_deterministic_and_brackets_auc():
    tasks = cal.load_tasks() if hasattr(cal, "load_tasks") else None
    from app.routing.tasks import load_tasks
    tasks = load_tasks()
    pol = preset("balanced", enabled=True)
    sc = cal.score_tasks(tasks, pol)
    a, b = cal.bootstrap_auc_ci(tasks, sc), cal.bootstrap_auc_ci(tasks, sc)
    assert a == b and a["low"] <= a["auc"] <= a["high"]


def test_revision_protocol_fit_on_train_only_and_gate():
    r = _rev().run()
    assert r["n_train"] + r["n_held_out"] == 174
    assert r["before"]["held_out"]["auc_easy_lt_hard"] < 0.5          # reproduces the inverted signal
    assert r["after"]["held_out"]["auc_easy_lt_hard"] > r["before"]["held_out"]["auc_easy_lt_hard"]
    ci = r["after"]["held_out"]["ci95"]
    assert ci[0] <= r["after"]["held_out"]["auc_easy_lt_hard"] <= ci[1]
    assert r["gate_router_not_constant"] is True
    assert len(r["before"]["routed_all_tasks_query_only"]) == 1       # was constant (tier 2 x174)
    assert 0.3 < r["sanity_shuffled_labels_held_out"]["auc"] < 0.7     # shuffled labels ~ chance
    assert r["after"]["policy"]["weights"]["ungrounded"] > 0
    assert r == _rev().run()                                           # deterministic
