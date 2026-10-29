"""memory_search mode='delegate': hand the query to the orchestrator as a run and return its id.

Opt-in (`ANAMNESIA_DELEGATE=1`, checked by app.routing.answer). The run executes in the background; poll it with
`get_delegate_status(run_id, project_path)`. Hooks (`get_orchestrator`, `resolve_project_path`) are looked up at call
time so tests can inject a FakeLauncher-backed orchestrator.

Launcher selection (default orchestrator): `ANAMNESIA_DELEGATE_LAUNCHER=terminal` -> TerminalLauncher over the
internal PTY manager (app.orchestration.pty_launcher; no UI/routes). `ANAMNESIA_DELEGATE_PROFILE` is REQUIRED and must
be a profile with kind=agent (ANA-195): unset/`shell`/unknown is refused with `profile_not_agent`/`profile_unknown`
(there is no usable default); anything else -> the headless
in-process launcher of `app.api.orchestration.get_orchestrator`.
"""
from __future__ import annotations

import importlib
import os
import threading

from app.orchestration.runs import RunError

DEFAULT_PRESET = "balanced"
_term_orch = None
_lock = threading.Lock()

# ANA-108: orchestration must not import the api layer. The composition root (app.api.*) may
# register providers via `set_provider`; otherwise the api module is resolved lazily by name at
# call time (importlib, no static import edge), preserving the old behaviour and test patches.
_providers: dict[str, object] = {}


def set_provider(name: str, fn) -> None:
    """name in {"workspace_registry", "terminal_manager", "default_orchestrator"}; fn() -> object."""
    _providers[name] = fn


def clear_providers() -> None:
    _providers.clear()


def _provide(name: str, module: str, attr: str):
    fn = _providers.get(name)
    if fn is not None:
        return fn()
    return getattr(importlib.import_module(module), attr)()


def delegate_enabled() -> bool:
    return os.getenv("ANAMNESIA_DELEGATE", "").strip().lower() in ("1", "true", "yes", "on")


def resolve_project_path(scope: str | None = None) -> str | None:
    """Project directory for a delegate run: a registered terminal project whose name/id matches the scope
    slug (`projeto:<slug>`), else env MG_PROJECT_PATH. Must be an existing directory; None otherwise."""
    slug = None
    if scope and ":" in scope:
        kind, _, rest = scope.partition(":")
        if kind.strip().lower() in ("projeto", "project"):
            slug = rest.strip().lower() or None
    if slug:
        try:
            for p in _provide("workspace_registry", "app.api.workspace", "get_registry").list():
                if slug in (p.name.lower(), p.id.lower()) and os.path.isdir(p.path):
                    return p.path
        except Exception:  # noqa: BLE001 - registry unavailable: fall through to the env var
            pass
    env = (os.getenv("MG_PROJECT_PATH") or "").strip()
    return env if env and os.path.isdir(env) else None


class DelegateError(ValueError):
    """Refusal before anything is launched. `reason_code` is what the search response reports (`delegate_error:<code>`)."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _agent_profile(profile_id: str):
    """ANA-195: terminal/agent delegation needs a profile with kind=agent; `shell` (or anything else) is refused."""
    from app.terminals.profiles import load_profiles
    p = load_profiles().get(profile_id)
    if p is None:
        raise DelegateError("profile_unknown")
    if p.kind != "agent":
        raise DelegateError("profile_not_agent")
    return p


def get_orchestrator():
    mode = os.getenv("ANAMNESIA_DELEGATE_LAUNCHER", "").strip().lower()
    if mode in ("terminal", "agent_cli"):
        global _term_orch
        profile = os.getenv("ANAMNESIA_DELEGATE_PROFILE", "").strip() or "shell"   # empty -> refused below (shell is kind=shell)
        _agent_profile(profile)                       # ANA-195: validated on EVERY call, never cached past a bad env
        with _lock:
            if _term_orch is not None and getattr(_term_orch, "_delegate_key", None) != (mode, profile):
                _term_orch = None
            if _term_orch is None:
                from app.orchestration.launchers import AgentCliLauncher, TerminalLauncher
                from app.orchestration.orchestrator import Orchestrator
                from app.routing.answer import get_availability, get_registry, usable_registry
                reg = get_registry()
                usable = usable_registry(reg, get_availability())
                if mode == "agent_cli":    # ANA-194: one headless CLI call per step (usage JSON), no PTY
                    launcher = AgentCliLauncher(registry=reg)
                else:
                    launcher = TerminalLauncher(_provide("terminal_manager", "app.orchestration.pty_launcher", "get_manager"),
                                                default_profile_id=profile)
                _term_orch = Orchestrator(launcher, registry=reg, profile_id=profile,
                                          available_providers={m.provider for m in usable.models})
                _term_orch._delegate_key = (mode, profile)
            return _term_orch
    return _provide("default_orchestrator", "app.api.orchestration", "get_orchestrator")


def run_delegate(query: str, scope: str | None, preset: str | None, project_path) -> dict:
    """Submit `query` as an orchestrator task. Returns {run_id, state, preset, project_path}. Raises
    ValueError/RunError (bad preset, empty task, bad path); the caller turns that into a fallback."""
    orch = get_orchestrator()
    preset = preset or os.getenv("ANAMNESIA_DELEGATE_PRESET", "").strip() or DEFAULT_PRESET
    run_id = orch.submit(query, preset, project_path)
    try:
        state = orch.get(run_id, project_path).state
    except RunError:
        state = "planned"
    return {"run_id": run_id, "state": state, "preset": preset, "project_path": str(project_path)}


def get_delegate_status(run_id: str, project_path=None) -> dict:
    """{run_id, state, reason, steps:[{step_id, role, state, model_id}], totals}; raises RunError if unknown."""
    if project_path is None:
        project_path = resolve_project_path(None)
    s = get_orchestrator().get(run_id, project_path).summary
    return {"run_id": s["run_id"], "state": s["state"], "reason": s.get("reason"),
            "steps": [{k: st.get(k) for k in ("step_id", "role", "state", "model_id")} for st in s.get("steps", [])],
            "totals": s.get("totals")}
