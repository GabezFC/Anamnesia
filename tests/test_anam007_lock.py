"""ANAM-007: lock de arquivo entre processos no memory_store (spawn, mesmo diretório)."""
from __future__ import annotations

import multiprocessing as mp
import threading
import time

import pytest

from app.memory_store import lifecycle
from app.memory_store.filelock import FileLock, LockTimeout, replace_with_retry
from app.memory_store.store import SavedContextStore


def _worker(root, nid, n, q):
    st = SavedContextStore(root, rate_per_min=100000)
    errs = []
    for _ in range(n):
        try:
            lifecycle.feedback(st, nid, "useful", None, author="t")
        except BaseException as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {e}")
    q.put(errs)


def _hold(path, secs, ready, q):
    lk = FileLock(path, timeout=5)
    with lk:
        ready.set()
        time.sleep(secs)
    q.put("ok")


@pytest.mark.parametrize("procs", [2, 4])
def test_multiprocess_feedback_80_of_80(tmp_path, procs):
    root = tmp_path / "saved_context"
    st = SavedContextStore(root, rate_per_min=100000)
    nid = st.save("Nota", "conteudo", ["t"], "p", "t")
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    ps = [ctx.Process(target=_worker, args=(str(root), nid, 80 // procs, q)) for _ in range(procs)]
    [p.start() for p in ps]
    errs = [e for _ in ps for e in q.get(timeout=120)]
    [p.join(30) for p in ps]
    assert errs == []
    assert SavedContextStore(root).get(nid).feedback_useful == 80
    assert len(lifecycle.feedback_events(st)) == 80


def test_reentrant_and_threads(tmp_path):
    lk = FileLock(tmp_path / "x.lock", timeout=2)
    with lk:
        with lk:
            pass
    total = []
    def run():
        with lk:
            v = len(total); time.sleep(0.001); total.append(v)
    ts = [threading.Thread(target=run) for _ in range(10)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert total == list(range(10))


def test_timeout_when_other_process_holds(tmp_path):
    path = tmp_path / "y.lock"
    ctx = mp.get_context("spawn")
    ready, q = ctx.Event(), ctx.Queue()
    p = ctx.Process(target=_hold, args=(str(path), 1.5, ready, q))
    p.start()
    assert ready.wait(30)
    with pytest.raises(LockTimeout):
        FileLock(path, timeout=0.3).acquire()
    assert q.get(timeout=30) == "ok"
    p.join(10)
    with FileLock(path, timeout=2):  # liberado após o término
        pass


def test_replace_retries_permission_error():
    calls = []
    def flaky(s, d):
        calls.append(1)
        if len(calls) < 4:
            raise PermissionError(13, "Acesso negado")
    replace_with_retry("a", "b", replace=flaky, base_delay=0.001)
    assert len(calls) == 4
    def always(s, d):
        raise PermissionError(13, "x")
    with pytest.raises(PermissionError):
        replace_with_retry("a", "b", replace=always, attempts=3, base_delay=0.001)
