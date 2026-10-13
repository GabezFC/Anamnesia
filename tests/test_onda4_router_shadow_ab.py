"""ANA-184 / 185 / 186 / 193: shadow routing, task-router prototype, escalation verifier, A/B. No model, no network."""
import pytest

from app.routing import ab, answer, shadow, task_router
from app.routing.escalation_verifier import (
    escalation_error_rates,
    verify_for_escalation,
    verify_with_ground_truth,
)
from app.routing.policy import preset
from app.routing.registry import load_registry

REG = load_registry()


# ----------------------------------------------------------------- ANA-186
def test_shadow_off_by_default(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_ROUTING_SHADOW", raising=False)
    shadow.stash(None)
    answer.plan_route("qual a porta do servico?", 0, "memory", "low")
    assert shadow.pop_pending() is None


def test_shadow_on_records_decision_without_calls(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ROUTING_SHADOW", "1")
    d, _reg, policy, _ = answer.plan_route("compare as versoes e explique por que mudou", 0, "memory", "low")
    assert d.model_id is None and policy.enabled is False            # real decision unchanged: routing still off
    s = shadow.pop_pending()
    assert s["executed"] is False and s["model_calls"] == 0
    assert len(s["reference"]["policy_hash"]) == 64 and len(s["alternative"]["policy_hash"]) == 64
    assert s["reference"]["policy_hash"] != s["alternative"]["policy_hash"] and s["registry_hash"]
    assert shadow.pop_pending() is None                              # consumed once


def test_shadow_persisted_in_metrics_json(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ROUTING_SHADOW", "1")
    answer.plan_route("x?", 0, "memory", "low")

    class DB:
        got = None

        def update_run_answer(self, run_id, ans, metrics, err):
            DB.got = metrics

    class GW:
        db = DB()

    class R:
        metrics = {}
        run_id = "r1"

    answer._persist(GW(), R(), {"mode_requested": "answer"})
    assert DB.got["shadow_decision"]["executed"] is False


def test_persist_has_no_shadow_key_when_off(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_ROUTING_SHADOW", raising=False)
    answer.plan_route("x?", 0, "memory", "low")

    class DB:
        got = None

        def update_run_answer(self, run_id, ans, metrics, err):
            DB.got = metrics

    class GW:
        db = DB()

    class R:
        metrics = {}
        run_id = "r1"

    answer._persist(GW(), R(), {"mode_requested": "answer"})
    assert "shadow_decision" not in DB.got


def test_shadow_alt_preset_env_and_divergence_report(monkeypatch):
    active = preset("balanced", enabled=True)
    rows = []
    for q, risk in [("qual a porta?", "low"), ("compare e explique por que a arquitetura mudou entre v1 e v2", "high"),
                    ("lista de portas", "medium")]:
        rows.append({"shadow_decision": shadow.compute_shadow(q, 0, "memory", risk, REG, active)})
    rep = shadow.divergence_report(rows)
    assert rep["n"] == 3 and rep["model_calls"] == 0
    assert set(rep["by_category"]) == {"risk", "task_kind", "tier_move"}
    assert 0.0 <= rep["divergence_rate"] <= 1.0
    monkeypatch.setenv("ANAMNESIA_ROUTING_SHADOW_PRESET", "max")
    assert shadow.compute_shadow("q", 0, "memory", "low", REG, active)["alternative"]["policy"] == "max"


def test_shadow_failure_never_raises(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ROUTING_SHADOW", "1")
    shadow.maybe_shadow("q", 0, "memory", "low", None, preset("balanced", enabled=True))   # registry None
    s = shadow.pop_pending()
    assert s is not None and s["executed"] is False


# ----------------------------------------------------------------- ANA-184
def test_task_router_is_shadow_only_and_fast():
    p = task_router.record_shadow("qual a porta do servico X?")
    assert p["shadow"] is True and p["calibrated"] is False and p["verdict"] == "HOLD"
    assert p["pipeline"] in task_router.PIPELINES
    cost = task_router.measure_decision_cost(["a?", "compare e explique " * 5, "def f(x): return x"], repeat=10)
    assert cost["within_budget"], cost
    assert cost["p95_ms"] <= 5.0


def test_task_router_high_risk_never_fast():
    assert task_router.plan_task("a?", 0, "high").pipeline != "fast_context"


# ----------------------------------------------------------------- ANA-185
SNIP = ["A porta do servico interno e 49120 dentro da rede docker. Fonte nota-a.md"]


def test_escalation_verifier_has_no_ground_truth_parameter():
    import inspect
    assert not any("expected" in k or "truth" in k for k in inspect.signature(verify_for_escalation).parameters)


def test_escalation_verifier_grounding_citation_schema():
    ok = verify_for_escalation("A porta do servico interno e 49120. nota-a.md", SNIP, ["nota-a.md"], require_citation=True)
    assert ok.accept
    bad = verify_for_escalation("O banco usa replicacao multimestre global.", SNIP, ["nota-a.md"])
    assert not bad.accept and "ungrounded_sentence" in bad.codes
    nocite = verify_for_escalation("A porta do servico interno e 49120.", SNIP, ["nota-a.md"], require_citation=True)
    assert "no_citation" in nocite.codes
    sch = {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}
    assert verify_for_escalation('{"path": "a.md"}', schema=sch).accept
    assert not verify_for_escalation('{"x": 1}', schema=sch).accept


def test_scoring_verifier_uses_ground_truth():
    assert verify_with_ground_truth("porta 49120", {"expected_facts": ["49120"]}).passed
    assert not verify_with_ground_truth("porta 1", {"expected_facts": ["49120"]}).passed
    assert verify_with_ground_truth("nao existe essa nota", {"answerable": False}).passed
    assert verify_with_ground_truth('{"a": "1"}', {"expected_json": {"a": "1"}}).passed
    assert not verify_with_ground_truth('{"a": "2"}', {"expected_json": {"a": "1"}}).passed


def test_error_rates_on_labelled_synthetic_records():
    # SYNTHETIC records: 10 accepted (2 wrong), 10 rejected (3 right). Not a measurement.
    recs = ([{"light_accept": True, "gt_correct": True}] * 8 + [{"light_accept": True, "gt_correct": False}] * 2
            + [{"light_accept": False, "gt_correct": True}] * 3 + [{"light_accept": False, "gt_correct": False}] * 7)
    r = escalation_error_rates(recs, "synthetic")
    assert r["false_accept"]["rate"] == 0.2 and r["false_reject"]["rate"] == 0.3
    assert r["claimable"] is False and r["note"] == "not a measurement"
    with pytest.raises(ValueError):
        escalation_error_rates(recs, "invented")
    assert escalation_error_rates([], "real")["false_accept"]["rate"] is None


# ----------------------------------------------------------------- ANA-193
def test_ab_off_by_default_and_low_risk_only(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_ROUTING_AB", raising=False)
    assert ab.assign("q", "low") == {"arm": "A", "eligible": False, "reason": "ab_disabled", "bucket": None}
    monkeypatch.setenv("ANAMNESIA_ROUTING_AB", "1")
    assert ab.assign("q", "high")["reason"] == "risk_not_low" and ab.assign("q", "medium")["arm"] == "A"
    assert ab.assign("q", "low")["eligible"] is True


def test_ab_bucket_deterministic_and_balanced():
    assert ab.bucket("Qual a porta?") == ab.bucket("Qual a porta?")
    arms = [ab.assign(f"pergunta numero {i} sobre modulo{i}", "low", force_enabled=True)["arm"] for i in range(2000)]
    share_b = arms.count("B") / len(arms)
    assert 0.44 < share_b < 0.56
    assert ab.assign("x", "low", share_b=0.0, force_enabled=True)["arm"] == "A"
    assert ab.assign("x", "low", share_b=1.0, force_enabled=True)["arm"] == "B"


def _recs(n, a_ground, b_ground, a_cost=1.0, b_cost=0.5):
    out = []
    for i in range(n):
        out.append({"arm": "A", "grounded": i < n * a_ground, "cost": a_cost + (i % 5) * 0.01})
        out.append({"arm": "B", "grounded": i < n * b_ground, "cost": b_cost + (i % 5) * 0.01})
    return out


def test_ab_guardrail_waits_oks_and_stops():
    assert ab.guardrail(_recs(10, 1, 1))["verdict"] == "WAIT"
    assert ab.guardrail(_recs(100, 0.9, 0.9))["verdict"] == "OK"
    assert ab.guardrail(_recs(200, 0.95, 0.6))["verdict"] == "STOP"


def test_ab_analyze_synthetic_never_claims_saving():
    r = ab.analyze(_recs(100, 0.9, 0.9), "cost", data_origin="synthetic")
    assert r["effect"]["excludes_zero"] is True and r["claimable_saving"] is False and r["verdict"] == "HOLD"
    r = ab.analyze(_recs(100, 0.9, 0.9), "cost", data_origin="real")
    assert r["claimable_saving"] is True and r["verdict"] == "ADOPT_CANDIDATE"
    r = ab.analyze(_recs(200, 0.95, 0.6), "cost", data_origin="real")
    assert r["verdict"] == "STOP" and r["claimable_saving"] is False


def test_ab_no_difference_is_hold():
    r = ab.analyze(_recs(100, 0.9, 0.9, 1.0, 1.0), "cost", data_origin="real")
    assert r["verdict"] == "HOLD" and not r["claimable_saving"]
