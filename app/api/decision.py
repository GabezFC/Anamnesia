"""Decision Engine API (ANAM-043): /api/decision/{status,config,decision,batch,history,metrics,evaluation}.

TODAS as rotas são loopback-only (`require_localhost`); as que podem acionar o JEV pago (`decision`, `batch`)
exigem também o guard completo de escrita local (mesma-origem + X-MG-Token), como os demais endpoints que
gastam. Respostas só carregam IDs/hashes e decisões — nunca o texto enviado. Sem rota que altere a config:
ela vem de MG_DECISION_* / arquivo (`MG_DECISION_CONFIG_FILE`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.decision.config import PROVIDERS, STRATEGIES
from app.decision.engine import get_engine
from app.decision.types import MAX_BATCH, MAX_ITEMS, MAX_TEXT_CHARS, OPS, DecisionRequest, Item
from app.services.security import require_local_write, require_localhost

router = APIRouter(prefix="/api/decision", dependencies=[Depends(require_localhost)])


class ItemIn(BaseModel):
    candidate_id: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., max_length=MAX_TEXT_CHARS)
    source: str = Field("", max_length=300)
    section: str = Field("", max_length=300)


class DecisionIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    items: list[ItemIn] = Field(..., min_length=1, max_length=MAX_ITEMS)
    op: str = Field("retrieval", pattern="^(" + "|".join(OPS) + ")$")
    project: str = Field("", max_length=64)
    provider: str | None = Field(None, pattern="^(" + "|".join(PROVIDERS) + ")$")
    strategy: str | None = Field(None, pattern="^(" + "|".join(STRATEGIES) + ")$")


class BatchIn(BaseModel):
    requests: list[DecisionIn] = Field(..., min_length=1, max_length=MAX_BATCH)


def _engine():
    eng = get_engine()
    try:   # reaproveita o JEV do gateway em execução (mesmo backend/cache); sem gateway, segue sem JEV (fallback explícito)
        from app.core.state import STATE
        g = STATE.require_gateway()
        eng.bind_jev(getattr(g, "jev", None))
    except Exception:  # noqa: BLE001
        pass
    return eng


def _req(b: DecisionIn) -> DecisionRequest:
    return DecisionRequest(b.query, [Item(i.candidate_id, i.text, i.source, i.section) for i in b.items],
                           b.op, b.project)


@router.get("/status")
def status():
    return _engine().status()


@router.get("/config")
def config():
    return _engine().cfg.to_public()


@router.post("/decision", dependencies=[Depends(require_local_write)])
def decision(body: DecisionIn):
    try:
        return _engine().decide(_req(body), provider=body.provider, strategy=body.strategy).to_public()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/batch", dependencies=[Depends(require_local_write)])
def batch(body: BatchIn):
    eng = _engine()
    try:
        return {"results": [r.to_public() for r in
                            (eng.decide(_req(b), provider=b.provider, strategy=b.strategy) for b in body.requests)]}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/history")
def history(limit: int = Query(50, ge=1, le=500), project: str | None = Query(None, max_length=64)):
    eng = get_engine()
    return {"records": eng.history.recent(limit, project), "total": eng.history.total,
            "privacy": "IDs/hashes apenas; nenhum texto de query ou candidato é guardado"}


@router.get("/metrics")
def metrics(project: str | None = Query(None, max_length=64)):
    return get_engine().history.metrics(project)


@router.get("/evaluation")
def evaluation():
    return get_engine().evaluation()
