import threading

import pytest

from app.schemas.models import Candidate
from app.services.jev import (DROP, KEEP, QUARANTINE, REVIEW, UNJUDGED, JevService, cache_key, route,
                              survives)
from config.jev import JevConfig


def cfg(**kw) -> JevConfig:
    base = dict(model="jev-1.13.0", mode="performance", context_budget=48000, state_budget=28000,
                relevance_threshold=0.78, review_threshold=0.55, injection_threshold=0.80,
                review_action="keep", second_pass=False, failure_mode="fail_open",
                max_concurrent_requests=1, max_retries=0, timeout_s=5.0)
    base.update(kw)
    return JevConfig(**base)


def cands(n=3):
    return [Candidate(candidate_id=f"c{i}", source_file=f"n{i}.md", section=f"S{i}",
                      snippet=f"conteúdo da nota {i} sobre o assunto", score=1.0 - i * 0.1,
                      content_hash=f"h{i}", meta={"secret": "should-not-be-sent"}) for i in range(n)]


class FakeBackend:
    """evaluate(state, questions) -> (answers, usage, model). Scores looked up by candidate id."""

    def __init__(self, rel=None, inj=None, usage=None, fail=False, rel_second=None):
        self.rel = rel or {}
        self.inj = inj or {}
        self.rel_second = rel_second
        self.usage = usage if usage is not None else {"input_tokens": 100, "output_tokens": 10}
        self.fail = fail
        self.calls: list[tuple[dict, dict]] = []
        self._lock = threading.Lock()

    def evaluate(self, state, questions):
        with self._lock:
            self.calls.append((state, questions))
            n = len(self.calls)
        if self.fail:
            raise RuntimeError("backend down")
        rel = self.rel_second if (self.rel_second is not None and n > 1) else self.rel
        answers = {}
        for name, q in questions.items():
            cid = q["instructions"]["candidate"]["id"]
            if name.startswith("rel_"):
                answers[name] = rel.get(cid, 0.9)
            elif name.startswith("inj_"):
                answers[name] = self.inj.get(cid, 0.0)
        return answers, dict(self.usage), "jev-1.13.0-resolved"


# -- routing -------------------------------------------------------------------
@pytest.mark.parametrize("rel,inj,expected", [
    (0.78, None, KEEP), (0.99, 0.1, KEEP), (0.7799, None, REVIEW), (0.55, None, REVIEW),
    (0.5499, None, DROP), (0.0, 0.0, DROP), (0.95, 0.80, QUARANTINE), (0.95, 0.7999, KEEP),
    (0.1, 0.9, QUARANTINE), (None, 0.9, UNJUDGED), (None, None, UNJUDGED),
])
def test_route_boundaries(rel, inj, expected):
    assert route(rel, inj, cfg()) == expected


def test_survives():
    keep, drop = cfg(review_action="keep"), cfg(review_action="drop")
    assert survives(KEEP, keep) and survives(KEEP, drop)
    assert survives(REVIEW, keep) and not survives(REVIEW, drop)
    for d in (DROP, QUARANTINE):
        assert not survives(d, keep)
    assert survives(UNJUDGED, cfg(failure_mode="fail_open"))
    assert not survives(UNJUDGED, cfg(failure_mode="fail_closed"))


# -- service -------------------------------------------------------------------
def test_one_request_per_batch_performance_only_rel():
    fb = FakeBackend()
    svc = JevService(cfg(), backend=fb)
    survivors, m = svc.evaluate("qual stack?", cands(3))
    assert len(fb.calls) == 1 and m.request_count == 1 and m.batch_sizes == [3]
    state, qs = fb.calls[0]
    assert state == {"query": "qual stack?"}
    assert set(qs) == {"rel_0", "rel_1", "rel_2"}
    assert len(survivors) == 3 and m.candidates_kept == 3
    assert m.jev_model_resolved == "jev-1.13.0-resolved"


def test_strict_mode_rel_and_inj_same_request():
    fb = FakeBackend(inj={"c1": 0.95})
    svc = JevService(cfg(mode="strict"), backend=fb)
    survivors, m = svc.evaluate("q", cands(2))
    assert len(fb.calls) == 1
    assert set(fb.calls[0][1]) == {"rel_0", "inj_0", "rel_1", "inj_1"}
    assert [c.candidate_id for c in survivors] == ["c0"]
    assert m.candidates_quarantined == 1


def test_payload_only_minimal_keys():
    fb = FakeBackend()
    JevService(cfg(mode="strict"), backend=fb).evaluate("q", cands(2))
    for q in fb.calls[0][1].values():
        assert set(q["instructions"]["candidate"]) == {"id", "source", "section", "snippet", "graph_score"}


def test_adaptive_batching_multiple_requests_and_usage_summed():
    fb = FakeBackend(usage={"input_tokens": 100, "output_tokens": 7})
    svc = JevService(cfg(context_budget=300), backend=fb)
    cs = cands(4)
    one_cost = svc.question_cost(cs[0])
    assert one_cost < 300  # sanity: each fits alone
    survivors, m = svc.evaluate("q", cs)
    assert len(fb.calls) > 1
    assert m.request_count == len(fb.calls) == len(m.batch_sizes)
    assert sum(m.batch_sizes) == 4
    assert m.input_tokens == 100 * len(fb.calls)
    assert m.output_tokens == 7 * len(fb.calls)
    assert len(survivors) == 4


def test_usage_none_makes_metric_unavailable():
    fb = FakeBackend(usage={"input_tokens": None, "output_tokens": None})
    _, m = JevService(cfg(), backend=fb).evaluate("q", cands(2))
    assert m.input_tokens is None and m.output_tokens is None


def test_backend_exception_fail_open_keeps_unjudged():
    fb = FakeBackend(fail=True)
    survivors, m = JevService(cfg(failure_mode="fail_open"), backend=fb).evaluate("q", cands(3))
    assert len(survivors) == 3
    assert all(c.decision == UNJUDGED for c in survivors)
    assert m.candidates_unjudged == 3 and m.errors


def test_backend_exception_fail_closed_drops():
    fb = FakeBackend(fail=True)
    survivors, m = JevService(cfg(failure_mode="fail_closed"), backend=fb).evaluate("q", cands(3))
    assert survivors == []
    assert m.candidates_unjudged == 3 and m.errors


def test_routing_applied_to_results():
    fb = FakeBackend(rel={"c0": 0.9, "c1": 0.6, "c2": 0.1})
    survivors, m = JevService(cfg(review_action="drop"), backend=fb).evaluate("q", cands(3))
    assert [c.candidate_id for c in survivors] == ["c0"]
    assert (m.candidates_kept, m.candidates_review, m.candidates_dropped) == (1, 1, 1)
    assert m.min_relevance == 0.1 and m.max_relevance == 0.9


def test_cache_get_and_put_used():
    c = cfg()
    cs = cands(3)
    store = {cache_key("q", cs[0], c): {"relevance": 0.95, "injection": None}}
    gets, puts = [], []

    def cget(k):
        gets.append(k)
        return store.get(k)

    def cput(k, v):
        puts.append((k, v))

    fb = FakeBackend(rel={"c1": 0.8, "c2": 0.2})
    svc = JevService(c, backend=fb, cache_get=cget, cache_put=cput)
    survivors, m = svc.evaluate("q", cs)
    assert len(gets) == 3
    assert m.cache_hits == 1 and m.cache_enabled
    sent_ids = {q["instructions"]["candidate"]["id"] for q in fb.calls[0][1].values()}
    assert sent_ids == {"c1", "c2"}
    assert {k for k, _ in puts} == {cache_key("q", cs[1], c), cache_key("q", cs[2], c)}
    assert cs[0].relevance == 0.95 and cs[0].decision == KEEP


def test_all_cached_makes_no_request():
    c = cfg()
    cs = cands(2)
    fb = FakeBackend()
    svc = JevService(c, backend=fb, cache_get=lambda k: {"relevance": 0.9, "injection": None})
    _, m = svc.evaluate("q", cs)
    assert fb.calls == [] and m.request_count == 0


def test_second_pass_only_reasks_review():
    fb = FakeBackend(rel={"c0": 0.9, "c1": 0.6, "c2": 0.1}, rel_second={"c1": 1.0})
    svc = JevService(cfg(second_pass=True), backend=fb)
    _, m = svc.evaluate("q", cands(3))
    assert len(fb.calls) == 2
    second_ids = {q["instructions"]["candidate"]["id"] for q in fb.calls[1][1].values()}
    assert second_ids == {"c1"}
    assert m.second_pass_requests == 1 and m.request_count == 2


def test_second_pass_skipped_without_review():
    fb = FakeBackend(rel={"c0": 0.9, "c1": 0.1})
    _, m = JevService(cfg(second_pass=True), backend=fb).evaluate("q", cands(2))
    assert len(fb.calls) == 1 and m.second_pass_requests == 0


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        JevService(cfg(mode="bogus"), backend=FakeBackend())
    with pytest.raises(ValueError):
        JevService(cfg(review_threshold=0.9, relevance_threshold=0.5), backend=FakeBackend())
