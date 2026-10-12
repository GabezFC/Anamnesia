"""Context Pack + memory evidence endpoints (ANA-147, 152, 153). Read-only except pack creation, which
runs a search (same cost as /memory/search) and stores a small JSON record."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services import context_pack as cp
from app.services.security import require_local_write

router = APIRouter(prefix="/api/memory")


class PackIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    pipeline: str = "baseline"
    max_results: int = Field(8, ge=1, le=20)
    scope: str | None = Field(None, max_length=500)
    context_budget: int | None = Field(None, ge=200, le=100000)
    ttl_s: int = Field(cp.DEFAULT_TTL_S, ge=60, le=30 * 24 * 3600)


def _gw():
    from app.api import routes
    return routes.gw()


@router.post("/packs", status_code=201, dependencies=[Depends(require_local_write)])
def create_pack(body: PackIn) -> dict:
    g = _gw()
    try:
        r = g.search(body.query, body.pipeline, body.max_results, context_budget=body.context_budget,
                     scope=body.scope, run_meta={"kind": "pack", "agent": "rest"})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    pack = cp.build_pack(g, r, scope=body.scope, token_budget=body.context_budget, ttl_s=body.ttl_s)
    cp.save_pack(pack)
    return {"pack_id": pack["id"], "run_id": r.run_id, "sources": len(pack["sources"]),
            "context_tokens": pack["context_tokens"], "token_budget": pack["token_budget"]}


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str) -> dict:
    try:
        pack = cp.load_pack(pack_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if pack is None:
        raise HTTPException(404, "pack não encontrado")
    return pack


@router.get("/packs/{pack_id}/verify")
def verify_pack(pack_id: str) -> dict:
    pack = get_pack(pack_id)
    return {"pack_id": pack_id, **cp.verify_pack(_gw(), pack)}


@router.get("/runs/{run_id}/evidence")
def run_evidence(run_id: str) -> dict:
    """ANA-153: which notes this run used and why (one SQL query)."""
    rows = _gw().db.run_evidence(run_id)
    if not rows:
        raise HTTPException(404, "run sem fontes ou inexistente")
    return {"run_id": run_id, "query": rows[0]["query"], "sources": [
        {k: r[k] for k in ("file", "section", "score", "decision", "tokens", "why")} for r in rows]}


@router.get("/evidence")
def note_evidence(file: str, limit: int = 20) -> dict:
    """ANA-153 (reverse): which runs/queries retrieved this note."""
    return {"file": file, "runs": _gw().db.runs_for_note(file, limit)}


@router.get("/runs/{run_id}/quality")
def run_quality(run_id: str) -> dict:
    """ANA-152: six signals side by side for a recorded run (no composite score)."""
    from app.services.near_dup import similarity
    rows = _gw().db.run_evidence(run_id)
    if not rows:
        raise HTTPException(404, "run sem fontes ou inexistente")
    g = _gw()
    idx = g.optimizer.provenance_index(g)
    stale, texts = 0, []
    for r in rows:
        f = idx.facts(r["file"]) if idx is not None else None
        if f is not None and (f.is_historical or f.is_expired()):
            stale += 1
        try:
            texts.append((r["file"], g.vault.read(r["file"])[:4000]))
        except Exception:  # noqa: BLE001
            pass
    red = max((similarity(a[1], b[1]) for i, a in enumerate(texts) for b in texts[i + 1:] if a[0] != b[0]), default=0.0)
    run = g.db.get_run(run_id) or {}
    m = run.get("metrics") or {}
    return {"run_id": run_id, "relevance": None, "redundancy": round(red, 4),
            "freshness_stale_share": round(stale / len(rows), 4), "injection_flags": m.get("documents_flagged"),
            "tokens": m.get("context_tokens"), "sources": len({r["file"] for r in rows}),
            "composite": None, "composite_blocked_by": "ANA-011/ANA-109: needs >=100 labelled items"}
