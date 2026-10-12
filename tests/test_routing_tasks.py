import json
import subprocess
import sys
from pathlib import Path

from app.routing.tasks import DEFAULT_PATH, DIFFICULTIES, Task, load_tasks, split_tasks
from app.routing.verifiers import verify_json_schema

ROOT = Path(__file__).resolve().parents[1]


def test_generator_deterministic(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_routing_tasks as g
    a = json.dumps(g.build(), sort_keys=True)
    b = json.dumps(g.build(), sort_keys=True)
    assert a == b
    on_disk = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    assert json.loads(a) == on_disk


def test_dataset_size_and_labels():
    tasks = load_tasks()
    assert len(tasks) >= 120
    assert len({t.id for t in tasks}) == len(tasks)
    assert {t.difficulty_label for t in tasks} == set(DIFFICULTIES)
    for d in DIFFICULTIES:
        assert sum(t.difficulty_label == d for t in tasks) >= 15


def test_ground_truth_ids_exist_in_manifest():
    man = json.loads((ROOT / "data/synthetic_vault/MANIFEST.json").read_text(encoding="utf-8"))
    paths = {f["path"] for f in man["facts"]}
    for t in load_tasks():
        if t.kind == "memory_qa":
            for p in t.ground_truth["gold_notes"]:
                assert (ROOT / "data/synthetic_vault" / p).exists() or p in paths, p
        elif t.kind == "extraction":
            assert t.ground_truth["expected_json"]["path"] in paths
            assert verify_json_schema(t.ground_truth["expected_json"], t.verifier["schema"]).passed


def test_difficulty_follows_objective_properties():
    tasks = {t.ground_truth["source_question"]: t for t in load_tasks() if t.kind == "memory_qa"}
    for t in tasks.values():
        if t.ground_truth["qclass"] in ("multi_hop", "unanswerable"):
            assert t.difficulty_label == "hard"
        assert t.ground_truth["answerable"] or t.verifier["type"] == "abstention"


def test_split_stratified_deterministic_disjoint():
    tasks = load_tasks()
    c1, e1 = split_tasks(tasks, seed=1)
    c2, e2 = split_tasks(tasks, seed=1)
    assert [t.id for t in c1] == [t.id for t in c2]
    assert not ({t.id for t in c1} & {t.id for t in e1})
    assert len(c1) + len(e1) == len(tasks)
    for d in DIFFICULTIES:
        n = sum(t.difficulty_label == d for t in tasks)
        assert abs(sum(t.difficulty_label == d for t in c1) - n / 2) <= 1


def test_task_validation():
    import pytest
    with pytest.raises(ValueError):
        Task("x", "memory_qa", "q", "impossible")
    with pytest.raises(ValueError):
        Task("x", "nope", "q", "easy")


# -- ANA-001 / ANA-002: anti-leak invariant ----------------------------------------------------
def _norm(text):
    import unicodedata
    t = unicodedata.normalize("NFKD", str(text).lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def test_no_expected_fact_in_query_invariant():
    """The expected fact must never be recoverable from the query (otherwise the benchmark is circular)."""
    leaks = []
    for t in load_tasks():
        if t.kind != "memory_qa":
            continue  # extraction tasks hand the note over by design; they do not test retrieval
        for f in t.ground_truth.get("expected_facts", []):
            if _norm(f) in _norm(t.query):
                leaks.append((t.id, f))
    assert not leaks, f"{len(leaks)} tasks leak the expected fact: {leaks[:5]}"


def test_no_gold_path_or_token_in_query():
    for t in load_tasks():
        if t.kind != "memory_qa":
            continue
        for p in t.ground_truth.get("gold_notes", []):
            assert p.lower() not in t.query.lower(), t.id
        hint_tokens = [w for w in t.ground_truth.get("expected_facts", [])]
        assert all(_norm(h) not in _norm(t.query) for h in hint_tokens), t.id


def test_leak_guard_rejects_a_leaking_query():
    sys.path.insert(0, str(ROOT / "scripts"))
    import gen_routing_tasks as g
    assert g.leaks('Qual o registro sobre "KrampusDB v7.111-rc0"?', ["KrampusDB v7.111-rc0"])
    assert not g.leaks("o snapshot foi validado contra ___", ["KrampusDB v7.111-rc0"])


def test_dataset_version_bumped_after_unleak():
    assert json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))["version"] >= 2
