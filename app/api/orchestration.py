"""Sub-agent orchestration API (/api/orchestration/*). Writes (POST) require the local-write guard."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.orchestration.config import OrchestrationConfigError
from app.orchestration.orchestrator import Orchestrator
from app.orchestration.runs import RunError, check_run_id
from app.services.security import require_local_write

router = APIRouter(prefix="/api/orchestration")

_orch: Orchestrator | None = None
_orch_lock = threading.Lock()


def get_orchestrator() -> Orchestrator:
    """Default: headless in-process launcher over the models usable right now. Tests override this dependency.

    (Terminal-session launching is wired later; see docs/ORCHESTRATION.md.)
    """
    global _orch
    with _orch_lock:
        if _orch is None:
            from app.orchestration.launchers import InProcessModelLauncher
            from app.routing.answer import get_availability, get_registry, usable_registry
            reg = get_registry()
            usable = usable_registry(reg, get_availability())
            _orch = Orchestrator(InProcessModelLauncher(usable), registry=reg,
                                 available_providers={m.provider for m in usable.models})
        return _orch


class RunBody(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    task: str = Field(min_length=1, max_length=20000)
    preset: str = Field(default="balanced", max_length=32)
    project_id: str | None = Field(default=None, max_length=128)
    budget_usd: float | None = Field(default=None, ge=0)


def _public(summary: dict) -> dict:
    return summary


@router.get("/presets")
def presets(orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    cfg = orch.config
    try:
        tiers = orch.registry.tiers()
        mapping = cfg.class_tiers(tiers)
    except Exception:  # noqa: BLE001 - registry unreadable: still describe the presets
        tiers, mapping = [], {c: [] for c in cfg.class_order}
    return {
        "presets": [{"name": p.name, "label": p.label, "routing_preset": p.routing_preset, "roles": p.roles}
                    for p in cfg.presets.values()],
        "class_order": list(cfg.class_order),
        "registry_tiers": tiers,
        "class_tiers": mapping,
        "limits": {"max_parallel_subagents": cfg.limits.max_parallel_subagents,
                   "budget_usd": cfg.limits.budget_usd,
                   "escalate_on_failures": cfg.limits.escalate_on_failures},
    }


@router.get("/runs")
def list_runs(path: str | None = None, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    return {"runs": [_public(s) for s in orch.list(path)]}


@router.post("/runs", status_code=202, dependencies=[Depends(require_local_write)])
def create_run(body: RunBody, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    try:
        rid = orch.submit(body.task, body.preset, body.path, project_id=body.project_id,
                          budget_usd=body.budget_usd)
    except OrchestrationConfigError as e:
        raise HTTPException(400, str(e)) from e
    except (RunError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"run_id": rid, "state": orch.get(rid).state}


def _find(orch: Orchestrator, run_id: str, path: str | None):
    try:
        check_run_id(run_id)
        return orch.get(run_id, path)
    except RunError as e:
        raise HTTPException(404, "run not found") from e


@router.get("/runs/{run_id}")
def get_run(run_id: str, path: str | None = None, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    run = _find(orch, run_id, path)
    return {**_public(run.summary), "events": run.events()[-200:]}


@router.post("/runs/{run_id}/cancel", dependencies=[Depends(require_local_write)])
def cancel_run(run_id: str, path: str | None = None, orch: Orchestrator = Depends(get_orchestrator)) -> dict:
    run = _find(orch, run_id, path)
    result = orch.cancel(run_id, path)
    return {"run_id": run.run_id, "result": result, "state": run.state}
