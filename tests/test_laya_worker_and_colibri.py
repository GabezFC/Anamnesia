"""ANAM-046: worker do Laya (laya_proc.py) e provider `colibri` do Decision Engine — 100% fakes.

O worker real só roda em integração marcada (venv do laya); aqui o subprocesso é um fake de pipes.
"""
from __future__ import annotations

import json
import queue
import threading

import pytest

from app.services.local_ai.laya_proc import LayaWorker, WorkerError, discover_python, worker_env


class FakeProc:
    """Imita subprocess.Popen com pipes de texto: responde 1 linha JSON por request."""

    def __init__(self, script_lines: list[str], fail_write: bool = False, die_after: int | None = None):
        self.lines = list(script_lines)
        self.fail_write = fail_write
        self.die_after = die_after
        self.written: list[str] = []
        self.killed = False
        self.stdin = self
        self.stdout = self
        self.returncode = None
        self._q: "queue.Queue[str | None]" = queue.Queue()

    # stdin
    def write(self, s: str) -> None:
        if self.fail_write:
            raise OSError("pipe quebrado (fake)")
        self.written.append(s)
        if self.die_after is not None and len(self.written) >= self.die_after:
            self._q.put(None)
            self.returncode = 1
            return
        # responde ecoando o id do request
        msg = json.loads(s)
        self._q.put(json.dumps({"id": msg["id"], "results": [{"answers": {}}]}) + "\n")

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self._q.put(None)

    # stdout
    def __iter__(self):
        return self

    def __next__(self):
        v = self._q.get(timeout=5)
        if v is None:
            raise StopIteration
        return v

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode or 0

    def kill(self):
        self.killed = True


def _mkworker(popen, load_timeout=5.0, timeout=5.0):
    w = LayaWorker("py", "ml", load_timeout_s=load_timeout, popen=popen)
    w.predict_batch([{"state": {}, "questions": {}}], None, timeout)
    return w


def test_worker_handshake_and_call():
    calls: list = []

    def popen(cmd, **kw):
        calls.append(cmd)
        return FakeProc([])   # handshake vem pelo FakeProc.write? não: handshake é a 1ª linha lida

    # handshake: injetamos um proc cuja stdout já tem a linha ready
    class ReadyProc(FakeProc):
        def __init__(self):
            super().__init__([])
            self._served = False

        def __next__(self):
            if not self._served:   # handshake chega DEPOIS do _start trocar a fila (como no Popen real)
                self._served = True
                return json.dumps({"ready": True, "load_ms": 12.0, "laya": "0.4.8",
                                   "models": ["multilingual"]}) + "\n"
            return super().__next__()

    def popen_ready(cmd, **kw):
        calls.append(cmd)
        return ReadyProc()

    w = _mkworker(popen_ready)
    assert w.alive() and w.starts == 1 and w.load_ms == 12.0 and w.laya_version == "0.4.8"
    assert len(calls) == 1 and calls[0][0] == "py"


def test_worker_env_is_scrubbed_and_offline():
    import os
    os.environ["_MG_SECRET_TEST"] = "x"
    try:
        env = worker_env()
        assert "_MG_SECRET_TEST" not in env and env["HF_HUB_OFFLINE"] == "1" and env["PYTHONUTF8"] == "1"
    finally:
        os.environ.pop("_MG_SECRET_TEST", None)


def test_worker_single_restart_on_death_then_error():
    attempts: list = []

    def popen(cmd, **kw):
        attempts.append(1)
        class Dying(FakeProc):
            def __init__(self):
                super().__init__([])
                self.die_after = 1   # morre no 1º request

            def __next__(self):
                if not self._served:
                    self._served = True
                    return json.dumps({"ready": True, "load_ms": 1.0, "laya": "0.4.8"}) + "\n"
                return super().__next__()
        return Dying()

    w = LayaWorker("py", "ml", load_timeout_s=5.0, popen=popen)
    with pytest.raises(WorkerError) as ei:
        w.predict_batch([{"state": {}}], None, 5.0)
    assert len(attempts) == 2   # 1 tentativa + 1 único reinício, nunca um laço
    assert ei.value.kind in ("died", "died_on_start")


def test_worker_call_timeout_drops_process():
    class Silent(FakeProc):
        def __init__(self):
            super().__init__([])
            self._served = False
            self._hold = threading.Event()   # stdout "aberto", sem dados: pump fica bloqueado

        def __next__(self):
            if not self._served:
                self._served = True
                return json.dumps({"ready": True, "load_ms": 1.0}) + "\n"
            self._hold.wait(timeout=10)
            raise StopIteration

        def write(self, s):
            pass   # nunca responde

    procs: list = []

    def popen(cmd, **kw):
        p = Silent()
        procs.append(p)
        return p

    w = LayaWorker("py", "ml", load_timeout_s=5.0, popen=popen)
    with pytest.raises(WorkerError) as ei:
        w.predict_batch([{"state": {}}], None, 0.2)
    assert ei.value.kind == "call_timeout" and not w.alive()


def test_worker_inference_error_does_not_restart():
    attempts: list = []

    class ErrProc(FakeProc):
        def __init__(self):
            super().__init__([])
            self._q.put(json.dumps({"ready": True, "load_ms": 1.0}) + "\n")

        def write(self, s):
            msg = json.loads(s)
            self._q.put(json.dumps({"id": msg["id"], "error": "RuntimeError: boom (fake)"}) + "\n")

    def popen(cmd, **kw):
        attempts.append(1)
        return ErrProc()

    w = LayaWorker("py", "ml", load_timeout_s=5.0, popen=popen)
    with pytest.raises(WorkerError) as ei:
        w.predict_batch([{"state": {}}], None, 5.0)
    assert ei.value.kind == "inference" and len(attempts) == 1


# ---------------------------------------------------------------- LayaBackend: disjuntor
def test_backend_breaker_opens_after_consecutive_failures(monkeypatch):
    from app.services.laya_decider import LayaBackend, LayaUnavailable
    from config.laya import LayaConfig

    cfg = LayaConfig(mode="inproc", breaker_failures=2, breaker_cooldown_s=60.0)

    class BoomBackend(LayaBackend):
        def resolve_mode(self):
            return "inproc"

        def _get_router(self):
            raise RuntimeError("torch quebrado (fake)")

    be = BoomBackend(cfg)
    for _ in range(2):
        with pytest.raises(LayaUnavailable):
            be.decide([{"text": "x"}], "relevance", {})
    with pytest.raises(LayaUnavailable) as ei:   # 3ª falha: circuito aberto, falha rápida
        be.decide([{"text": "x"}], "relevance", {})
    assert "circuito aberto" in str(ei.value)
    be.reset_circuit()
    with pytest.raises(LayaUnavailable):
        be.decide([{"text": "x"}], "relevance", {})   # fechado de novo: erro real volta


def test_worker_mode_end_to_end_real_venv():
    """INTEGRAÇÃO REAL (rotulada): exige o venv do laya nesta máquina; senão NÃO-EXECUTADO."""
    py, _origin = discover_python("")
    if not py:
        pytest.skip("sem venv do laya — NÃO-EXECUTADO")
    import time as _t
    from config.paths import PACKAGE_ROOT
    w = LayaWorker(py, str(PACKAGE_ROOT / "data" / "local_ai" / "models" / "laya-multilingual"),
                   load_timeout_s=180.0)
    try:
        t0 = _t.perf_counter()
        out = w.predict_batch([{"state": {"text": "O build usa cache."}, "questions": {
            "q": {"type": "choice", "instructions": "Relevante?", "criteria": {"A": "sim", "B": "nao"}}}}],
            16, 60.0)
        assert out and "answers" in out[0]
        assert w.starts == 1   # o worker não morre entre chamadas
        w.predict_batch([{"state": {"text": "de novo"}, "questions": {
            "q": {"type": "choice", "instructions": "Relevante?", "criteria": {"A": "sim", "B": "nao"}}}}],
            16, 60.0)
        assert w.starts == 1
    finally:
        w.stop()


# ---------------------------------------------------------------- Colibri no Decision Engine
class FakeColibriJev:
    """Imita JevService o suficiente para o JEVDecisionProvider."""

    def __init__(self, relevance=0.9):
        self.relevance = relevance
        self.cfg = type("C", (), {"mode": "performance", "injection_threshold": 0.8})()

    def evaluate(self, query, candidates):
        for c in candidates:
            c.relevance = self.relevance
        from app.services.jev import JevMetrics
        return candidates, JevMetrics(request_count=1, input_tokens=10, output_tokens=0)


def _engine_with_colibri(monkeypatch, relevance=0.9):
    from app.decision.config import load_config
    from app.decision.engine import DecisionEngine

    class Factory:
        def __call__(self):
            return FakeColibriJev(relevance)

    fake_factory = Factory()

    import app.services.colibri as col_mod
    monkeypatch.setattr(col_mod, "colibri_provider_factory", lambda cfg=None: fake_factory)
    monkeypatch.setattr(col_mod, "colibri_status", lambda cfg=None, probe=None:
                        {"provider": "colibri", "enabled": True, "label": "MEASURED", "available": True,
                         "reachable": True, "models": ["jev-latest"]})
    eng = DecisionEngine(load_config())
    return eng


def test_colibri_provider_decides_local(monkeypatch):
    from app.decision.types import KEEP
    eng = _engine_with_colibri(monkeypatch)
    from app.decision.types import DecisionRequest, Item
    r = eng.decide(DecisionRequest("q", [Item("a", "texto", "", "")]), provider="colibri")
    assert r.provider == "colibri" and r.items[0].decision == KEEP and r.items[0].provider == "colibri"


def test_colibri_provider_unavailable_when_disabled(monkeypatch):
    import app.services.colibri as col_mod

    def factory():
        from app.services.colibri import ColibriUnavailable
        raise ColibriUnavailable("Colibri desabilitado (fake)")

    monkeypatch.setattr(col_mod, "colibri_provider_factory", lambda cfg=None: factory)
    monkeypatch.setattr(col_mod, "colibri_status", lambda cfg=None, probe=None:
                        {"provider": "colibri", "enabled": False, "label": "OFF", "available": False})
    from app.decision.config import load_config
    from app.decision.engine import DecisionEngine
    from app.decision.types import DecisionRequest, Item, UNJUDGED
    eng = DecisionEngine(load_config())
    r = eng.decide(DecisionRequest("q", [Item("a", "texto", "", "")]))   # cai no fallback do engine
    assert r.items[0].decision in (UNJUDGED, "KEEP", "REVIEW", "DROP")   # fallback explícito, nunca exceção


def test_colibri_status_has_unmeasured_quality_note():
    from app.services.colibri import colibri_status
    st = colibri_status()
    assert "NAO MEDIDO" in st.get("quality", "") or st["label"] == "OFF"
