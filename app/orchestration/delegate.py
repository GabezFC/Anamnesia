"""memory_search mode='delegate': hand the query to the orchestrator as a run and return its id.

Opt-in (`ANAMNESIA_DELEGATE=1`, checked by app.routing.answer). The run executes in the background; poll it with
`get_delegate_status(run_id, project_path)`. Hooks (`get_orchestrator`, `resolve_project_path`) are looked up at call
time so tests can inject a FakeLauncher-backed orchestrator.

Launcher selection (default orchestrator): `ANAMNESIA_DELEGATE_LAUNCHER=terminal` -> TerminalLauncher over the
workspace Terminal Manager (profile `ANAMNESIA_DELEGATE_PROFILE`, default `shell`); anything else -> the headless
in-process launcher of `app.api.orchestration.get_orchestrator`.
"""
from __future__ import annotations

import os
import threading

from app.orchestration.runs import RunError

DEFAULT_PRESET = "balanced"
_term_orch = None
_lock = threading.Lock()


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
            from app.api.workspace import get_registry
            for p in get_registry().list():
                if slug in (p.name.lower(), p.id.lower()) and os.path.isdir(p.path):
                    return p.path
        except Exception:  # noqa: BLE001 - registry unavailable: fall through to the env var
            pass
    env = (os.getenv("MG_PROJECT_PATH") or "").strip()
    return env if env and os.path.isdir(env) else None


def get_orchestrator():
    if os.getenv("ANAMNESIA_DELEGATE_LAUNCHER", "").strip().lower() == "terminal":
        global _term_orch
        with _lock:
            if _term_orch is None:
                from app.api.workspace import get_manager
                from app.orchestration.launchers import TerminalLauncher
                from app.orchestration.orchestrator import Orchestrator
                from app.routing.answer import get_availability, get_registry, usable_registry
                reg = get_registry()
                usable = usable_registry(reg, get_availability())
                profile = os.getenv("ANAMNESIA_DELEGATE_PROFILE", "").strip() or "shell"
                _term_orch = Orchestrator(TerminalLauncher(get_manager(), default_profile_id=profile),
                                          registry=reg, profile_id=profile,
                                          available_providers={m.provider for m in usable.models})
            return _term_orch
    from app.api.orchestration import get_orchestrator as default
    return default()


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
