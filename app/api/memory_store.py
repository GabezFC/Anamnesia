"""REST API for agent-saved context (Fase 7). Router is wired in app/main.py by the orchestrator.

State-changing calls (POST/DELETE) go through `require_local_write` (loopback + Origin +
X-MG-Token). So does GET /export, since it hands out the whole memory. Listing/reading single
notes is open, like the rest of the read API.
Wiring (orchestrator): `app.include_router(memory_store.router)` and call
`attach_saved_context(gateway)` (app/memory_store/index.py) where the MemoryGateway is created.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.memory_store import lifecycle
from app.memory_store.store import SavedContextError, get_store
from app.services.security import require_local_write

router = APIRouter(prefix="/api/memory")


class NoteIn(BaseModel):
    title: str = Field(..., max_length=200)
    content: str
    tags: list[str] = Field(default_factory=list)
    project: str | None = None
    source_agent: str | None = None
    # ANA-145 (schema v2) -- all optional
    kind: str | None = None
    expires_at: str | None = None
    ttl_days: float | None = None
    confidence: float | None = None
    source: str | None = None
    supersedes: str | None = None
    # ANA-148
    dedupe: str | None = None


class UpdateIn(BaseModel):
    title: str | None = Field(None, max_length=200)
    content: str | None = None
    tags: list[str] | None = None
    kind: str | None = None
    status: str | None = None
    expires_at: str | None = None
    ttl_days: float | None = None
    confidence: float | None = None
    source: str | None = None


class FeedbackIn(BaseModel):
    verdict: str
    reason: str | None = Field(None, max_length=500)
    author: str | None = Field(None, max_length=80)


class RollbackIn(BaseModel):
    version: str


class ReapIn(BaseModel):
    dry_run: bool = True


class ConsolidateIn(BaseModel):
    apply: bool = False


class MigrateIn(BaseModel):
    dry_run: bool = True


class ImportIn(BaseModel):
    overwrite: bool = False


class ForgetIn(BaseModel):
    confirm: bool = False


def _http(exc: SavedContextError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


def _after_change() -> None:
    """Best effort: make the running gateway (if any) see the change immediately."""
    try:
        from app.core.state import STATE  # ANA-106
        gw = STATE.gateway
        if gw is not None:
            from app.memory_store.index import reindex
            reindex(gw)
    except Exception:  # noqa: BLE001 - the freshness check will catch up anyway
        pass


@router.post("/notes", status_code=201, dependencies=[Depends(require_local_write)])
def create_note(body: NoteIn) -> dict:
    v2 = body.model_dump(exclude={"title", "content", "tags", "project", "source_agent", "dedupe"}, exclude_none=True)
    try:
        res = lifecycle.save_checked(get_store(), body.title, body.content, body.tags, body.project,
                                     body.source_agent, dedupe=body.dedupe, **v2)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    # `id` first and always present (older clients read only that); the rest is additive (ANA-148)
    return {"id": res["id"], "saved": res["saved"], "similar": res["similar"], "action": res["action"],
            **({"duplicate_of": res["duplicate_of"]} if res.get("duplicate_of") else {})}


@router.get("/notes")
def list_notes(project: str | None = None, tag: str | None = None, kind: str | None = None,
               include_expired: bool = True) -> dict:
    notes = get_store().list(project=project, tag=tag, kind=kind, include_expired=include_expired)
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


# ---- ANA-150: update / versions / rollback / trash --------------------------------------------
@router.put("/notes/{note_id}", dependencies=[Depends(require_local_write)])
def update_note(note_id: str, body: UpdateIn) -> dict:
    try:
        n = get_store().update(note_id, **body.model_dump(exclude_none=True))
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return n.to_dict(with_content=False)


@router.get("/notes/{note_id}/history")
def note_history(note_id: str) -> dict:
    try:
        return {"id": note_id, "versions": lifecycle.history(get_store(), note_id)}
    except SavedContextError as exc:
        raise _http(exc) from exc


@router.get("/notes/{note_id}/diff", response_class=PlainTextResponse)
def note_diff(note_id: str, a: str, b: str = "current") -> str:
    try:
        return lifecycle.diff(get_store(), note_id, a, b)
    except SavedContextError as exc:
        raise _http(exc) from exc


@router.post("/notes/{note_id}/rollback", dependencies=[Depends(require_local_write)])
def note_rollback(note_id: str, body: RollbackIn) -> dict:
    try:
        n = lifecycle.rollback(get_store(), note_id, body.version)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return n.to_dict(with_content=False)


@router.post("/notes/{note_id}/feedback", dependencies=[Depends(require_local_write)])
def note_feedback(note_id: str, body: FeedbackIn, request: Request) -> dict:
    try:
        res = lifecycle.feedback(get_store(), note_id, body.verdict, body.reason,
                                 author=body.author or request.headers.get("X-MG-Client"), source="user")
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return res


@router.get("/trash")
def trash() -> dict:
    return {"items": lifecycle.trash_list(get_store())}


@router.post("/trash/{trash_id}/restore", dependencies=[Depends(require_local_write)])
def trash_restore(trash_id: str) -> dict:
    try:
        nid = lifecycle.restore(get_store(), trash_id)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return {"restored": nid}


@router.post("/reap", dependencies=[Depends(require_local_write)])
def reap(body: ReapIn) -> dict:
    res = lifecycle.reap(get_store(), dry_run=body.dry_run)
    if not body.dry_run:
        _after_change()
    return res


# ---- ANA-156/158/160/162: lifecycle reports ---------------------------------------------------
@router.get("/audit")
def audit() -> dict:
    return lifecycle.audit(get_store())


@router.get("/usefulness")
def usefulness() -> dict:
    return {"notes": lifecycle.usefulness(get_store())}


@router.get("/contradictions")
def contradictions() -> dict:
    return {"candidates": lifecycle.contradictions(get_store())}


@router.post("/consolidate", dependencies=[Depends(require_local_write)])
def consolidate(body: ConsolidateIn) -> dict:
    res = lifecycle.consolidate(get_store(), apply=body.apply)
    if body.apply:
        _after_change()
    return res


@router.post("/migrate", dependencies=[Depends(require_local_write)])
def migrate(body: MigrateIn) -> dict:
    res = lifecycle.migrate_v1(get_store(), dry_run=body.dry_run)
    if not body.dry_run:
        _after_change()
    return res


@router.get("/feedback/events", dependencies=[Depends(require_local_write)])
def feedback_events(reviewed: bool | None = None) -> dict:
    return {"events": lifecycle.feedback_events(get_store(), only_reviewed=reviewed)}


@router.post("/feedback/events/{event_id}/review", dependencies=[Depends(require_local_write)])
def review_event(event_id: int, request: Request) -> dict:
    try:
        return lifecycle.review_feedback(get_store(), event_id, request.headers.get("X-MG-Client") or "local-user")
    except SavedContextError as exc:
        raise _http(exc) from exc


# ---- ANA-163: portable JSONL ------------------------------------------------------------------
@router.get("/export.jsonl", dependencies=[Depends(require_local_write)])
def export_jsonl() -> Response:
    return Response(lifecycle.export_jsonl(get_store()), media_type="application/x-ndjson",
                    headers={"Content-Disposition": 'attachment; filename="anamnesia-memory.jsonl"'})


@router.post("/import", dependencies=[Depends(require_local_write)])
async def import_jsonl(request: Request, overwrite: bool = False) -> dict:
    raw = (await request.body()).decode("utf-8", errors="replace")
    try:
        res = lifecycle.import_jsonl(get_store(), raw, overwrite=overwrite)
    except SavedContextError as exc:
        raise _http(exc) from exc
    _after_change()
    return res
