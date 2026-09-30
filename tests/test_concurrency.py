"""Concurrency safety of MemoryGateway (§5.4 da proposta 2026-09-28, item 8 de
pendencias-e-riscos-abertos).

`active_scope` used to be plain instance state on the ONE MemoryGateway instance every request
shares (app/api/routes.py `_state["gateway"]`). FastAPI runs sync endpoints in a thread pool, so two
concurrent searches with different scopes could interleave set/read/reset and leak one request's
project scope into another's results. These tests prove the ContextVar-backed replacement
(app/gateway/memory_gateway.py) keeps concurrent scopes isolated, both across native threads and
across asyncio tasks (which each get their own copied context, e.g. via `asyncio.to_thread`).
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.gateway.memory_gateway import MemoryGateway
from app.services.scope import parse_scope, project_of


class MockJevBackend:
    """Judges everything as highly relevant, so scope is the only thing that can filter."""

    def evaluate(self, state, questions):
        n = len([k for k in questions if k.startswith("rel_")])
        answers = {f"rel_{i}": 0.95 for i in range(n)}
        return answers, {"input_tokens": n * 300, "output_tokens": n * 18}, "mock-jev"


@pytest.fixture(scope="module")
def gateway():
    gw = MemoryGateway(jev_backend=MockJevBackend())
    if not gw.vault.exists():
        pytest.skip("vault não disponível neste ambiente")
    gw.jev = gw.make_jev(gw.jev_cfg, cache=False)
    gw.warm()
    return gw


QUERY = "arquitetura decisao driver banco de dados"


def test_active_scope_is_contextvar_backed():
    """The public attribute keeps working (get/set), but is not stored on the instance __dict__."""
    gw = MemoryGateway.__new__(MemoryGateway)  # no __init__: this test only touches the property
    assert "active_scope" not in vars(gw)
    scope = parse_scope("projeto:x")
    gw.active_scope = scope
    assert gw.active_scope is scope
    assert "active_scope" not in vars(gw)


def test_active_scope_thread_isolation():
    """Two native threads setting `gw.active_scope` concurrently must never see each other's value.

    A plain instance attribute would race here (last writer wins for both readers); a ContextVar
    gives each thread's default (fresh) context its own slot.
    """
    gw = MemoryGateway.__new__(MemoryGateway)
    scope_a, scope_b = parse_scope("projeto:a"), parse_scope("projeto:b")
    seen = {}
    barrier = threading.Barrier(2)

    def worker(name, scope):
        gw.active_scope = scope
        barrier.wait(timeout=5)  # force both threads to have set before either reads
        time.sleep(0.02)
        seen[name] = gw.active_scope

    t1 = threading.Thread(target=worker, args=("a", scope_a))
    t2 = threading.Thread(target=worker, args=("b", scope_b))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert seen["a"] is scope_a
    assert seen["b"] is scope_b


def test_active_scope_asyncio_task_isolation():
    """Two asyncio tasks running the same sync-style scope set/read via `asyncio.to_thread` (which
    copies the calling context into the worker thread) must not contaminate each other either.
    """
    gw = MemoryGateway.__new__(MemoryGateway)
    scope_a, scope_b = parse_scope("projeto:a"), parse_scope("projeto:b")

    def set_and_read(scope):
        gw.active_scope = scope
        time.sleep(0.02)
        return gw.active_scope

    async def main():
        return await asyncio.gather(
            asyncio.to_thread(set_and_read, scope_a),
            asyncio.to_thread(set_and_read, scope_b),
        )

    result_a, result_b = asyncio.run(main())
    assert result_a is scope_a
    assert result_b is scope_b


def test_concurrent_scoped_searches_do_not_leak(gateway):
    """End-to-end: two concurrent gateway.search() calls with different project scopes must each
    return only sources from their own project, never the other's.
    """
    info = gateway.projects()
    if len(info["projects"]) < 2:
        pytest.skip("vault com menos de dois projetos")
    slug_a, slug_b = info["projects"][0]["slug"], info["projects"][1]["slug"]
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def run(name, slug):
        try:
            results[name] = gateway.search(QUERY, pipeline="baseline", max_results=10,
                                           persist=False, scope=f"projeto:{slug}")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(f"t{i}", s))
              for i, s in enumerate([slug_a, slug_b] * 5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len(results) == len(threads)
    for name, r in results.items():
        idx = int(name[1:])
        expected_slug = slug_a if idx % 2 == 0 else slug_b
        assert r.metrics["scope"] == f"projeto:{expected_slug}"
        for s in r.sources:
            assert project_of(s.file) == expected_slug, f"vazamento de escopo em {name}: {s.file}"
