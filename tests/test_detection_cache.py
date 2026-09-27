"""Tests for the stale-while-revalidate cache around model detection.

The probes hit the network (~9 s), so the only acceptable behaviour on the request path is:
never block except on a genuinely cold cache. These tests use a fake probe with a real sleep to
prove the request path does not wait for it.
"""
from __future__ import annotations

import time

import pytest

from app.adapters import registry


@pytest.fixture(autouse=True)
def _clear_cache(monkeypatch):
    """Every test starts from a cold cache and a quiet refresh flag."""
    registry._models_cache["at"] = 0.0
    registry._models_cache["value"] = None
    registry._models_refreshing.clear()
    yield
    registry._models_cache["at"] = 0.0
    registry._models_cache["value"] = None
    registry._models_refreshing.clear()


def _slow_probe(calls: list, delay: float = 0.25, tag: str = "v"):
    def probe():
        calls.append(tag)
        time.sleep(delay)
        return {"ollama": {"available": True, "models": [f"{tag}{len(calls)}"]}}
    return probe


def test_cold_start_blocks_once_then_serves_from_cache(monkeypatch):
    calls: list = []
    monkeypatch.setattr(registry, "detect_models", _slow_probe(calls, 0.25))

    t0 = time.perf_counter()
    first = registry._detect_models_cached()
    cold = time.perf_counter() - t0
    assert cold >= 0.2, "a cold cache has nothing to serve, it must block"

    t0 = time.perf_counter()
    second = registry._detect_models_cached()
    warm = time.perf_counter() - t0
    assert warm < 0.05, f"a warm read must not block (took {warm:.3f}s)"
    assert second == first
    assert len(calls) == 1


def test_expired_cache_serves_stale_without_blocking(monkeypatch):
    calls: list = []
    monkeypatch.setattr(registry, "detect_models", _slow_probe(calls, 0.25))
    stale = registry._detect_models_cached()          # cold: 1 probe
    registry._models_cache["at"] = time.monotonic() - (registry._MODELS_TTL_S + 1)

    t0 = time.perf_counter()
    served = registry._detect_models_cached()          # expired: must NOT block
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.05, f"expired cache must serve stale immediately (took {elapsed:.3f}s)"
    assert served == stale, "the stale value is what gets served"

    # the background refresh eventually replaces it
    deadline = time.time() + 3
    while time.time() < deadline and registry._models_refreshing.is_set():
        time.sleep(0.02)
    assert len(calls) == 2, "a background refresh should have run"
    fresh = registry._detect_models_cached()
    assert fresh != stale, "after the background refresh the cached value is updated"


def test_concurrent_expired_reads_trigger_only_one_refresh(monkeypatch):
    import threading
    calls: list = []
    monkeypatch.setattr(registry, "detect_models", _slow_probe(calls, 0.3))
    registry._detect_models_cached()                   # cold: 1 probe
    registry._models_cache["at"] = time.monotonic() - (registry._MODELS_TTL_S + 1)

    threads = [threading.Thread(target=registry._detect_models_cached) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    deadline = time.time() + 3
    while time.time() < deadline and registry._models_refreshing.is_set():
        time.sleep(0.02)
    assert len(calls) == 2, f"8 concurrent readers must cause exactly 1 refresh, got {len(calls) - 1}"


def test_refresh_true_is_synchronous(monkeypatch):
    calls: list = []
    monkeypatch.setattr(registry, "detect_models", _slow_probe(calls, 0.2))
    registry._detect_models_cached()
    t0 = time.perf_counter()
    registry._detect_models_cached(refresh=True)
    assert time.perf_counter() - t0 >= 0.15, "refresh=True must wait for a live probe"
    assert len(calls) == 2


def test_failing_probe_does_not_break_the_request_path(monkeypatch):
    calls: list = []
    monkeypatch.setattr(registry, "detect_models", _slow_probe(calls, 0.05))
    good = registry._detect_models_cached()
    registry._models_cache["at"] = time.monotonic() - (registry._MODELS_TTL_S + 1)

    def boom():
        calls.append("boom")
        raise RuntimeError("probe down")

    monkeypatch.setattr(registry, "detect_models", boom)
    served = registry._detect_models_cached()   # triggers a failing background refresh
    assert served == good, "a broken probe must still serve the last good value"

    deadline = time.time() + 2
    while time.time() < deadline and registry._models_refreshing.is_set():
        time.sleep(0.02)
    assert registry._detect_models_cached() == good
    assert not registry._models_refreshing.is_set(), "the refresh flag must be released on error"
