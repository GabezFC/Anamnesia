"""ANA-092/093/098/110/111/112: benchmark scoring & sampling fixes."""
from __future__ import annotations

import pytest

from app.benchmark import routing_bench as rb
from app.routing import metrics as M
from app.routing.registry import ModelEntry
from app.routing.tasks import Task, load_tasks
from app.routing.verifiers import (extract_cited_ids, match_cited_to_retrieved, verify_citation,
                                   verify_fact_match)


def _task(tid="t1", kind="memory_qa", diff="easy", answerable=True, vtype="fact_match+citation", facts=("42",)):
    return Task(id=tid, kind=kind, query="q?", difficulty_label=diff,
                ground_truth={"answerable": answerable, "expected_facts": list(facts)},
                verifier={"type": vtype})


# ------------------------------------------------------------------ ANA-092
@pytest.mark.parametrize("answer,fact", [
    ("o timeout foi 1420ms", "42"),        # 42 inside 1420
    ("versao 3.5 do modulo", "3"),         # 3 prefix of 3.5
    ("versao 1.3", "3"),                   # 3 suffix of 1.3
    ("pi vale 13.145", "3.14"),
    ("a trust chain", "rust"),
    ("v1.2.3 lançada", "1.2"),
    ("valor 4200", "42"),
])
def test_fact_match_rejects_substring_false_positives(answer, fact):
    assert not verify_fact_match(answer, [fact]).passed


@pytest.mark.parametrize("answer,fact", [
    ("o valor é 42.", "42"),
    ("valores: 42, 43", "42"),
    ("(42)", "42"),
    ("Rust é bom", "rust"),
    ("timeout de 157 ms", "157ms"),
    ("versão 1,5 do módulo", "versao 1.5"),
    ("a=42", "42"),
    ("KrampusDB v7.111-rc0 validado", "krampusdb v7.111-rc0"),
])
def test_fact_match_keeps_true_positives(answer, fact):
    assert verify_fact_match(answer, [fact]).passed


# ------------------------------------------------------------------ ANA-111
def test_cited_ids_extraction_and_suffix_matching():
    ans = "Segundo 20-Dev-IA/Reranker-Local-023.md e tambem outra.md (veja x/y.md)."
    assert extract_cited_ids(ans) == ["20-dev-ia/reranker-local-023.md", "outra.md", "x/y.md"]
    assert match_cited_to_retrieved(["reranker-local-023.md", "z.md"], ["20-Dev-IA/reranker-local-023.md"]) == \
        ["20-dev-ia/reranker-local-023.md", "z.md"]


def test_verify_task_citation_subset_of_retrieved():
    t = _task()
    ok = rb.verify_task(t, "O valor é 42. Fonte: a/n.md", ["a/n.md", "b/m.md"])
    assert ok.passed and ok.details["citation_checked"] is True
    bad = rb.verify_task(t, "O valor é 42. Fonte: inventada.md", ["a/n.md"])
    assert not bad.passed and bad.failure_code == "citation_not_retrieved"
    none = rb.verify_task(t, "O valor é 42.", ["a/n.md"])
    assert not none.passed and none.failure_code == "no_citation"


def test_verify_task_without_retrieval_skips_citation_explicitly():
    r = rb.verify_task(_task(), "O valor é 42.", None)
    assert r.passed and r.details["citation_checked"] is False


def test_verify_task_plain_fact_match_task_ignores_citation():
    r = rb.verify_task(_task(vtype="fact_match"), "42", ["a.md"])
    assert r.passed and "citation_checked" not in r.details


def test_citation_verified_rate_counts_only_checked_and_ok():
    recs = [{"kind": "memory_qa", "citation_task": True, "citation_checked": True, "citation_ok": True},
            {"kind": "memory_qa", "citation_task": True, "citation_checked": True, "citation_ok": False},
            {"kind": "memory_qa", "citation_task": True, "citation_checked": False},
            {"kind": "extraction", "citation_task": False}]
    r = rb.citation_verified_rate(recs)
    assert (r["citation_tasks"], r["checked"], r["verified"]) == (3, 2, 1)
    assert r["verified_rate"] == round(1 / 3, 4)


def test_verify_citation_primitive_unchanged():
    assert verify_citation(["a"], ["a", "b"]).passed


# ------------------------------------------------------------------ ANA-112
def test_cell_sampling_covers_every_cell_and_beats_difficulty_only():
    tasks = load_tasks()
    for n in (6, 10, 20):
        cell = rb.sample_tasks(tasks, n, 42)
        legacy = rb.sample_tasks(tasks, n, 42, strata="difficulty")
        cov, cov_legacy = rb.sample_coverage(tasks, cell), rb.sample_coverage(tasks, legacy)
        assert cov["coverage"] == 1.0 and len(cell) == n
        assert cov["cells_covered"] >= cov_legacy["cells_covered"]
    cov20 = rb.sample_coverage(tasks, rb.sample_tasks(tasks, 20, 42))
    share = sum(1 for t in tasks if not t.ground_truth.get("answerable", True)) / len(tasks)
    assert cov20["unanswerable_in_sample"] >= int(20 * share)   # abstentions at least proportional (floor)


def test_sampling_is_deterministic_and_full_when_n_large():
    tasks = load_tasks()
    assert [t.id for t in rb.sample_tasks(tasks, 20, 7)] == [t.id for t in rb.sample_tasks(tasks, 20, 7)]
    assert len(rb.sample_tasks(tasks, 10_000, 7)) == len(tasks)


def test_min_per_cell_is_respected_with_tiny_n():
    tasks = load_tasks()
    s = rb.sample_tasks(tasks, 3, 1)
    assert len(s) == 3 and len({rb.task_cell(t) for t in s}) == 3


# ------------------------------------------------------------------ ANA-093
def test_answerable_is_an_independent_dimension_in_records_and_metrics():
    ta, tu = _task("a", diff="hard"), _task("u", diff="hard", answerable=False, vtype="abstention", facts=())
    ra, ru = rb._base_record(ta, "S", False), rb._base_record(tu, "S", False)
    assert ra["answerable_class"] == "answerable" and ru["answerable_class"] == "unanswerable"
    ra["solved"], ru["solved"] = True, False
    ba = M.by_answerable([ra, ru])
    assert ba["answerable"]["n"] == 1 and ba["unanswerable"]["n"] == 1
    assert ba["unanswerable"]["solved"] == 0
    assert "by_answerable" in M.summarize_strategy([ra, ru])


def test_group_compare_by_answerable_class():
    def rec(tid, cls, strat, solved):
        return {"task_id": tid, "answerable_class": cls, "strategy": strat, "solved": solved, "cost": 1.0,
                "final_cost": 1.0, "tokens": 10, "cost_origin": "measured"}
    dyn = [rec("1", "answerable", "D", True), rec("2", "unanswerable", "D", True)]
    base = [rec("1", "answerable", "B", True), rec("2", "unanswerable", "B", False)]
    g = M.group_compare(dyn, base, "answerable_class")
    assert set(g) == {"answerable", "unanswerable"}


# ------------------------------------------------------------------ ANA-110

def test_repeat_cache_keys_rep0_is_historical_and_reps_differ():
    k0 = rb.ResultCache.content_key("p", "m", {"a": 1}, "r")
    assert k0 == rb.ResultCache.content_key("p", "m", {"a": 1}, "r", rep=0)
    ks = {rb.ResultCache.content_key("p", "m", {"a": 1}, "r", rep=i) for i in range(3)}
    assert len(ks) == 3


def test_repeat_report_std_between_reps():
    recs = []
    pattern = {0: [True, True, True, True], 1: [True, True, False, False], 2: [True, False, False, False]}
    for rp, outs in pattern.items():
        for i, ok in enumerate(outs):
            recs.append({"strategy": "S", "rep": rp, "task_id": f"t{i}", "solved": ok, "simulated": False})
    rr = rb.repeat_report(recs)["S"]
    assert rr["reps"] == 3 and rr["rates"] == [1.0, 0.5, 0.25]
    assert rr["std"] == pytest.approx(0.3819, abs=1e-3)
    assert rr["unstable_tasks"] == 3 and rr["tasks"] == 4


def test_repeat_report_ignores_simulated():
    assert rb.repeat_report([{"strategy": "S", "rep": 0, "task_id": "a", "solved": True, "simulated": True}]) == {}


def test_run_benchmark_repeats_executes_each_rep_once_with_a_flaky_runner():
    from app.routing.registry import load_registry
    reg = load_registry()
    models = reg.models[:2]
    calls = {"n": 0}

    class Flaky(rb.StubRunner):
        simulated = False

        def __call__(self, task, entry):
            calls["n"] += 1
            out = super().__call__(task, entry)
            out.simulated = False
            if calls["n"] % 2:
                out.answer = "resposta incorreta"
            return out

    tasks = [t for t in load_tasks() if t.kind == "extraction"][:3]
    res = rb.run_benchmark(tasks, models, Flaky(), [rb.STATIC_CHEAP], repeats=3)
    reps = sorted({r["rep"] for r in res.records if r["strategy"] == rb.STATIC_CHEAP})
    assert reps == [0, 1, 2]
    assert calls["n"] == 9                      # 3 tasks x 3 reps, each (task, model, rep) executed once
    assert res.meta["repeats"] == 3 and rb.STATIC_CHEAP in res.meta["repeat_report"]
    res1 = rb.run_benchmark(tasks, models, rb.StubRunner(), [rb.STATIC_CHEAP])
    assert res1.meta["repeats"] == 1 and "repeat_report" not in res1.meta
