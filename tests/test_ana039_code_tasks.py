"""ANA-039: code tasks with sandboxed verify_tests_pass."""
import json
import sys
from pathlib import Path

import pytest

from app.benchmark import routing_bench as rb
from app.routing.tasks import load_tasks

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_code_tasks  # noqa: E402

PATH = ROOT / "benchmark" / "routing_tasks_code.json"


def test_json_is_up_to_date():
    assert json.loads(PATH.read_text(encoding="utf-8")) == json.loads(json.dumps(gen_code_tasks.build()))


def test_at_least_20_code_tasks_and_no_leak():
    tasks = load_tasks(PATH)
    assert len(tasks) >= 20 and all(t.kind == "code" for t in tasks)
    for t in tasks:  # the reference solution body must not be in the prompt
        body = t.ground_truth["reference"].splitlines()[1].strip()
        assert body not in t.query


@pytest.mark.parametrize("task", load_tasks(PATH), ids=lambda t: t.id)
def test_reference_passes(task):
    r = rb.verify_task(task, "```python\n" + task.ground_truth["reference"] + "```")
    assert r.passed is True, r


def test_controls_fail():
    tasks = load_tasks(PATH)
    res = rb.run_controls(tasks, [rb.NULL_ECHO, rb.EMPTY])
    for strat in (rb.NULL_ECHO, rb.EMPTY):
        assert res[strat]["passed"] == 0 and not res[strat]["invalid_verifier"]


def test_wrong_and_hanging_answers_fail():
    t = load_tasks(PATH)[0]
    fn = t.ground_truth["function"]
    assert rb.verify_task(t, f"def {fn}(*a):\n    return 12345\n").passed is False
    t2 = Task_with_timeout(t)
    assert rb.verify_task(t2, f"def {fn}(*a):\n    while True:\n        pass\n").passed is False


def Task_with_timeout(t):
    from dataclasses import replace
    return replace(t, verifier={**t.verifier, "timeout_s": 2})
