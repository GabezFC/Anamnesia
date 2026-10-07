"""Session launchers for sub-agents.

`SessionLauncher` is the seam to the Terminal Manager (wired later). The orchestrator talks to roles through
files in the run directory: before `send`, it passes env overrides (ANAMNESIA_RUN_DIR, ANAMNESIA_STEP_DIR,
ANAMNESIA_ROLE, ANAMNESIA_MODEL_ID, ...); the role writes `<step_dir>/result.md` and `<step_dir>/status.json`
({"ok": bool, "error": str|None, "input_tokens": int|None, "output_tokens": int|None, "latency_ms": float|None}).
Usage the provider did not report is null, never estimated.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class SessionLauncher(Protocol):
    def launch(self, project_id: str | None, profile_id: str | None, env_overrides: dict, cwd: str) -> str: ...
    def send(self, session_id: str, text: str) -> None: ...
    def close(self, session_id: str) -> None: ...
    def is_alive(self, session_id: str) -> bool: ...


def _write_step(step_dir: Path, result: str | None, status: dict) -> None:
    step_dir.mkdir(parents=True, exist_ok=True)
    if result is not None:
        (step_dir / "result.md").write_text(result, encoding="utf-8")
    (step_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")


class FakeLauncher:
    """Test double. `behavior(call)` may return {"ok", "error", "input_tokens", "output_tokens", "result",
    "latency_ms", "block": threading.Event}; default = success with the given token counts (or None).

    Every call is recorded in `.calls` (role, step, model_id, env, text). Tracks `max_concurrent`.
    """

    def __init__(self, behavior: Callable[[dict], dict] | None = None, input_tokens: int | None = None,
                 output_tokens: int | None = None, delay_s: float = 0.0):
        self.behavior = behavior
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.delay_s = delay_s
        self.calls: list = []
        self.sessions: dict = {}
        self.closed: list = []
        self.max_concurrent = 0
        self._active = 0
        self._n = 0
        self._lock = threading.Lock()

    def launch(self, project_id, profile_id, env_overrides, cwd) -> str:
        with self._lock:
            self._n += 1
            sid = f"fake-{self._n}"
            self.sessions[sid] = {"env": dict(env_overrides), "cwd": cwd, "alive": True,
                                  "project_id": project_id, "profile_id": profile_id}
        return sid

    def send(self, session_id: str, text: str) -> None:
        s = self.sessions[session_id]
        env = s["env"]
        call = {"session": session_id, "role": env.get("ANAMNESIA_ROLE"), "step": env.get("ANAMNESIA_STEP"),
                "model_id": env.get("ANAMNESIA_MODEL_ID"), "env": env, "text": text}
        with self._lock:
            self.calls.append(call)
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        try:
            out = dict(self.behavior(call)) if self.behavior else {}
            blk = out.get("block")
            if blk is not None:
                blk.wait(10)
            if self.delay_s:
                time.sleep(self.delay_s)
            ok = out.get("ok", True)
            status = {"ok": ok, "error": None if ok else out.get("error", "fake failure"),
                      "input_tokens": out.get("input_tokens", self.input_tokens),
                      "output_tokens": out.get("output_tokens", self.output_tokens),
                      "latency_ms": out.get("latency_ms", 1.0)}
            result = out.get("result", f"[fake {call['role']}] done") if ok else None
            _write_step(Path(env["ANAMNESIA_STEP_DIR"]), result, status)
        finally:
            with self._lock:
                self._active -= 1

    def close(self, session_id: str) -> None:
        with self._lock:
            if session_id in self.sessions:
                self.sessions[session_id]["alive"] = False
            self.closed.append(session_id)

    def is_alive(self, session_id: str) -> bool:
        return bool(self.sessions.get(session_id, {}).get("alive"))


class InProcessModelLauncher:
    """Headless: runs a role by calling a model adapter directly (no terminal, no tools).

    The role can only produce text (findings, a proposed diff, a verdict); it does not touch files.
    `adapter_factory(entry)` must return an object with `.generate(prompt, max_tokens=...)` returning a
    GenerationResult-like object. The default factory builds the real adapter (network!) lazily.
    """

    def __init__(self, registry, adapter_factory: Callable | None = None, max_tokens: int = 1200,
                 avail: dict | None = None):
        self.registry = registry
        self.max_tokens = max_tokens
        self.avail = avail
        self._factory = adapter_factory
        self.sessions: dict = {}
        self._n = 0
        self._lock = threading.Lock()

    def _make(self, entry):
        if self._factory is not None:
            return self._factory(entry)
        from app.routing.answer import make_adapter   # lazy: real adapters only when really used
        return make_adapter(entry, self.avail)

    def launch(self, project_id, profile_id, env_overrides, cwd) -> str:
        with self._lock:
            self._n += 1
            sid = f"inproc-{self._n}"
            self.sessions[sid] = {"env": dict(env_overrides), "cwd": cwd, "alive": True}
        return sid

    def send(self, session_id: str, text: str) -> None:
        env = self.sessions[session_id]["env"]
        step_dir = Path(env["ANAMNESIA_STEP_DIR"])
        status = {"ok": False, "error": None, "input_tokens": None, "output_tokens": None, "latency_ms": None}
        result = None
        try:
            entry = self.registry.get(env["ANAMNESIA_MODEL_ID"])
            g = self._make(entry).generate(text, max_tokens=self.max_tokens)
            status.update(input_tokens=g.input_tokens, output_tokens=g.output_tokens, latency_ms=g.latency_ms)
            if g.error or not (g.answer or "").strip():
                status["error"] = (g.error or "empty answer")[:200]
            else:
                status["ok"], result = True, g.answer
        except Exception as e:  # noqa: BLE001 - a failing model is a failed step, not a crash
            status["error"] = f"{type(e).__name__}: {str(e)[:150]}"
        _write_step(step_dir, result, status)

    def close(self, session_id: str) -> None:
        if session_id in self.sessions:
            self.sessions[session_id]["alive"] = False

    def is_alive(self, session_id: str) -> bool:
        return bool(self.sessions.get(session_id, {}).get("alive"))
