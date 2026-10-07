"""REST API for agent-saved context (Fase 7). Router is wired in app/main.py by the orchestrator.

State-changing calls (POST/DELETE) go through `require_local_write` (loopback + Origin +
X-MG-Token). So does GET /export, since it hands out the whole memory. Listing/reading single
notes is open, like the rest of the read API.
Wiring (orchestrator): `app.include_router(memory_store.router)` and call
`attach_saved_context(gateway)` (app/memory_store/index.py) where the MemoryGateway is created.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.memory_store.store import SavedContextError, get_store
from app.services.security import require_local_write

router = APIRouter(prefix="/api/memory")


class NoteIn(BaseModel):
    title: str = Field(..., max_length=200)
    content: str
    tags: list[str] = Field(default_factory=list)
    project: str | None = None
    source_agent: str | None = None


class ForgetIn(BaseModel):
    confirm: bool = False


def _http(exc: SavedContextError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _after_change() -> None:
    """Best effort: make the running gateway (if any) see the change immediately."""
    try:
        from app.api import routes
        gw = routes._state.get("gateway")
        if gw is not None:
            from app.memory_store.index import reindex
            reindex(gw)
    except Exception:  # noqa: BLE001 - the freshness check will catch up anyway
        pass


@router.post("/notes", status_code=201, dependencies=[Depends(require_local_write)])
def create_note(body: NoteIn) -> dict:
    try:
        note_id = get_store().save(body.title, body.content, body.tags, body.project, body.source_agent)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return {"id": note_id}


@router.get("/notes")
def list_notes(project: str | None = None, tag: str | None = None) -> dict:
    notes = get_store().list(project=project, tag=tag)
    return {"count": len(notes), "notes": [n.to_dict(with_content=False) for n in notes]}


@router.get("/export", dependencies=[Depends(require_local_write)])
def export_notes() -> Response:
    return Response(get_store().export_zip(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="saved_context.zip"'})


@router.get("/notes/{note_id}")
def get_note(note_id: str) -> dict:
    try:
        return get_store().get(note_id).to_dict()
    except SavedContextError as exc:
        raise _http(exc) from exc


@router.delete("/notes/{note_id}", dependencies=[Depends(require_local_write)])
def delete_note(note_id: str) -> dict:
    try:
        get_store().delete(note_id)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return {"deleted": note_id}


@router.post("/forget", dependencies=[Depends(require_local_write)])
def forget(body: ForgetIn) -> dict:
    try:
        n = get_store().forget_all(confirm=body.confirm)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return {"deleted": n}
