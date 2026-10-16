"""ANAM-036 (benchmark local por fingerprint) e ANAM-037 (hotset com decaimento). Sem rede."""
from __future__ import annotations

import json
import socket

import pytest

from app.benchmark import local_bench as lb
from app.gateway.optimizer import HotSet, MemoryOptimizer, ResultCache
from config.optimizer import OptimizerConfig


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("rede real proibida nos testes")
    monkeypatch.setattr(socket, "create_connection", boom)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def fake_transport(clock, ttfts, decode_s=1.0, usage=True, tokens=11):
    """Cada chamada consome o proximo ttft; avanca o relogio falso."""
    it = iter(ttfts)

    def run(request):
        assert request["stream"] is True
        clock.t += next(it)
        yield {"choices": [{"delta": {"content": "a"}}]}
        clock.t += decode_s
        yield {"choices": [{"delta": {"content": "b"}}]}
        if usage:
            yield {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": tokens}}
    return run


HW = {"hw_fingerprint": "abc123def4567890", "os": {"system": "X"}, "cpu": {"name": "c"}, "ram": {}, "gpus": []}


def test_cold_discarded_and_warm_mean(tmp_path):
    clk = FakeClock()
    doc = lb.run_benchmark(fake_transport(clk, [2.0, 0.5, 0.3]), "m", "http://u:p@h:1/v1?k=s", runs=3, hw=HW,
                           out_dir=tmp_path, clock=clk)
    e = doc["results"]["m"]
    assert e["cold"]["ttft_ms"] == 2000.0
    assert e["warm"]["n"] == 2 and e["warm"]["ttft_ms"] == 400.0          # cold fora da media
    assert e["cold_over_warm_ttft"] == 5.0
    assert e["warm"]["prefill_tok_s"] == pytest.approx((100 / 0.5 + 100 / 0.3) / 2, rel=1e-2)
    assert e["warm"]["decode_tok_s"] == 10.0                               # (11-1)/1s
    assert e["endpoint"] == "http://h:1/v1"                                # sem user:senha/query


def test_file_per_fingerprint_and_merge(tmp_path):
    clk = FakeClock()
    lb.run_benchmark(fake_transport(clk, [1, 1, 1]), "m1", hw=HW, out_dir=tmp_path, clock=clk)
    lb.run_benchmark(fake_transport(clk, [1, 1, 1]), "m2", hw=HW, out_dir=tmp_path, clock=clk)
    f = tmp_path / "abc123def4567890.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    assert set(data["results"]) == {"m1", "m2"} and data["hw_fingerprint"] == "abc123def4567890"
    assert lb.load_cached("abc123def4567890", "m1", tmp_path)["model"] == "m1"
    assert lb.load_cached("abc123def4567890", "zzz", tmp_path) is None


def test_missing_usage_is_labelled_not_measured(tmp_path):
    clk = FakeClock()
    doc = lb.run_benchmark(fake_transport(clk, [1, 1, 1], usage=False), "m", hw=HW, out_dir=tmp_path, clock=clk)
    w = doc["results"]["m"]["warm"]
    assert w["prefill_tok_s"] == lb.NOT_MEASURED and w["decode_tok_s"] == lb.NOT_MEASURED
    assert w["ttft_ms"] == 1000.0


def test_endpoint_failure_is_data_not_exception(tmp_path):
    def bad(request):
        raise ConnectionError("down")
        yield  # pragma: no cover
    doc = lb.run_benchmark(bad, "m", hw=HW, out_dir=tmp_path, write=False)
    e = doc["results"]["m"]
    assert e["runs_ok"] == 0 and e["cold"] == lb.NOT_MEASURED and e["warm"] == lb.NOT_MEASURED
    assert doc["path"] is None and not list(tmp_path.iterdir())


def test_uses_real_fingerprint_when_hw_absent(tmp_path, monkeypatch):
    import app.services.hw_profile as hp
    monkeypatch.setattr(hp, "detect_hardware", lambda *a, **k: HW)
    clk = FakeClock()
    doc = lb.run_benchmark(fake_transport(clk, [1, 1, 1]), "m", out_dir=tmp_path, clock=clk)
    assert doc["hw_fingerprint"] == "abc123def4567890"


# ------------------------------------------------------------------ hotset
def test_hotset_decays_exponentially():
    clk = FakeClock()
    hs = HotSet(half_life_s=100, clock=clk)
    for _ in range(4):
        hs.touch_query("old")
    clk.t = 200                                   # 2 meias-vidas -> 4 * 0.25 = 1
    assert hs.query_score("old") == pytest.approx(1.0)
    hs.touch_query("new")
    hs.touch_query("new")
    assert [k for k, _, _ in hs.top_queries(2)] == ["new", "old"]


def test_hotset_bounded_and_notes():
    clk = FakeClock()
    hs = HotSet(max_items=8, clock=clk)
    for i in range(50):
        clk.t += 1
        hs.touch_notes([f"n{i}.md"])
    assert len(hs._n) <= 8
    assert hs.top_notes(1)[0][0] == "n49.md"


def test_cache_eviction_protects_hot_entry():
    hs = HotSet()
    for _ in range(5):
        hs.touch_query("hot")
    c = ResultCache(size=3, ttl_s=100.0)
    c.score_fn = lambda key: hs.query_score(key[1])
    c.put(("v", "hot"), 1)
    c.put(("v", "cold1"), 2)
    c.put(("v", "cold2"), 3)
    c.put(("v", "cold3"), 4)                      # estoura: LRU puro tiraria "hot"
    assert c.get(("v", "hot")) == 1
    assert c.protected_evictions == 1


def test_flag_default_off_and_on(monkeypatch):
    monkeypatch.delenv("MG_HOTSET", raising=False)
    assert MemoryOptimizer(OptimizerConfig()).hotset is None
    monkeypatch.setenv("MG_HOTSET", "1")
    opt = MemoryOptimizer(OptimizerConfig())
    assert opt.hotset is not None and opt.cache.score_fn is not None
