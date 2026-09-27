"""Regression: second-pass JEV usage accounting (bug reported by the test subagent)."""
from config.jev import JevConfig
from app.schemas.models import Candidate
from app.services.jev import JevService


class Backend:
    def __init__(self, usages):
        self.usages = list(usages)
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        usage = self.usages.pop(0)
        return {k: 0.6 for k in questions}, usage, "jev-1.13.0"  # 0.6 -> REVIEW


def _cands():
    return [Candidate(f"c{i}", f"n{i}.md", "S", f"texto {i} relevante", 0.5) for i in range(3)]


def test_second_pass_counts_input_and_output():
    b = Backend([{"input_tokens": 100, "output_tokens": 10}, {"input_tokens": 40, "output_tokens": 4}])
    _, m = JevService(JevConfig(second_pass=True), backend=b).evaluate("q", _cands())
    assert b.calls == 2 and m.second_pass_requests == 1
    assert (m.input_tokens, m.output_tokens) == (140, 14)


def test_second_pass_missing_usage_is_unavailable():
    b = Backend([{"input_tokens": 100, "output_tokens": 10}, {"input_tokens": None, "output_tokens": None}])
    _, m = JevService(JevConfig(second_pass=True), backend=b).evaluate("q", _cands())
    assert m.input_tokens is None and m.output_tokens is None
