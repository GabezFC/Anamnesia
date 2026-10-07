"""Workspace API (Fase 10): projects, read-only file explorer, launch profiles, terminal sessions + WebSocket.

Security (default deny, see docs/TERMINALS.md):
  * terminals work only when the bind host is loopback (or ANAMNESIA_ALLOW_REMOTE_TERMINALS=1);
  * every state-changing REST call (and the sensitive reads) uses `require_local_write`;
  * the WebSocket needs token in subprotocol `tok.<token>` + Origin == own origin + loopback client,
    otherwise it is closed with 4403 BEFORE accepting (nothing about the session is revealed).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.services.security import (get_or_create_local_token, is_local_client, require_local_write,
                                   require_localhost)
from app.terminals import worktrees as wt
from app.terminals.manager import SessionLimitError, SessionNotFound, TerminalManager
from app.terminals.profiles import Profile, ProfileError, ProfileUnavailable, load_profiles
from app.terminals.projects import (PathEscapeError, ProjectError, ProjectRegistry, list_dir,
                                    search_content, search_names)

router = APIRouter(prefix="/api")
audit = logging.getLogger("anamnesia.terminals.audit")

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "[::1]"}
WS_CLOSE_FORBIDDEN = 4403
WS_CLOSE_NOT_FOUND = 4404
MAX_WS_MESSAGE = 1024 * 1024
ALLOW_REMOTE_ENV = "ANAMNESIA_ALLOW_REMOTE_TERMINALS"


# ------------------------------------------------------------------ gates / deps
def _bind_host() -> str:
    try:
        from config.benchmark import BenchmarkConfig

        return str(BenchmarkConfig().host)
    except Exception:  # config unreadable => be strict
        return os.environ.get("MG_HOST", "0.0.0.0")


def remote_allowed() -> bool:
    return os.environ.get(ALLOW_REMOTE_ENV, "") == "1"


def terminals_enabled() -> bool:
    return remote_allowed() or _bind_host().strip().lower() in LOOPBACK_HOSTS


_manager: TerminalManager | None = None
_registry: ProjectRegistry | None = None
_profiles: dict[str, Profile] | None = None
_init_lock = threading.Lock()


def get_manager() -> TerminalManager:
    global _manager
    with _init_lock:
        if _manager is None:
            _manager = TerminalManager()
        return _manager


def get_registry() -> ProjectRegistry:
    global _registry
    with _init_lock:
        if _registry is None:
            _registry = ProjectRegistry()
        return _registry


def get_profiles() -> dict[str, Profile]:
    global _profiles
    with _init_lock:
        if _profiles is None:
            _profiles = load_profiles()
        return _profiles


def _err(status: int, code: str, message: str, hint: str = "") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "hint": hint}}, status_code=status)


def _terminals_disabled() -> JSONResponse:
    return _err(403, "terminals_disabled", "terminais desativados: o servidor não está em loopback",
                f"suba com MG_HOST=127.0.0.1 ou defina {ALLOW_REMOTE_ENV}=1 (assumindo o risco)")


# ------------------------------------------------------------------ projects
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=4096)


@router.get("/projects", dependencies=[Depends(require_localhost)])
def list_projects(reg: ProjectRegistry = Depends(get_registry)):
    return {"projects": [p.to_dict() for p in reg.list()]}


@router.post("/projects", status_code=201, dependencies=[Depends(require_local_write)])
def add_project(body: ProjectIn, reg: ProjectRegistry = Depends(get_registry)):
    try:
        return reg.add(body.name, body.path).to_dict()
    except ProjectError as e:
        return _err(422, "invalid_project", str(e), "informe o caminho de um diretório existente")


@router.delete("/projects/{project_id}", dependencies=[Depends(require_local_write)])
def remove_project(project_id: str, reg: ProjectRegistry = Depends(get_registry),
                   mgr: TerminalManager = Depends(get_manager)):
    if not reg.remove(project_id):
        return _err(404, "not_found", "projeto não encontrado")
    for s in mgr.list():  # sessions of a removed project make no sense; files are untouched
        if s.project_id == project_id:
            mgr.close(s.id, "project_removed")
    return {"removed": True}


@router.get("/projects/{project_id}/files", dependencies=[Depends(require_local_write)])
def project_files(project_id: str, path: str = "", q: str = "", content: int = 0,
                  reg: ProjectRegistry = Depends(get_registry)):
    proj = reg.get(project_id)
    if proj is None:
        return _err(404, "not_found", "projeto não encontrado")
    try:
        if q and content:
            return search_content(proj.path, q[:200], path)
        if q:
            return search_names(proj.path, q[:200], path)
        return list_dir(proj.path, path)
    except PathEscapeError:
        return _err(403, "path_escape", "caminho fora do projeto")
    except (ProjectError, OSError):
        return _err(404, "not_found", "diretório não encontrado")


# ------------------------------------------------------------------ worktrees (T10.7)
class WorktreeIn(BaseModel):
    branch: str = Field(min_length=1, max_length=200)


_WT_STATUS = {"not_a_git_repo": 422, "invalid_branch": 422, "not_found": 404, "conflict": 409,
              "dirty": 409, "forbidden": 403}


def _wt_err(e: wt.WorktreeError) -> JSONResponse:
    return _err(_WT_STATUS.get(e.code, 422), e.code, str(e))


@router.get("/projects/{project_id}/worktrees", dependencies=[Depends(require_local_write)])
def list_project_worktrees(project_id: str, reg: ProjectRegistry = Depends(get_registry)):
    proj = reg.get(project_id)
    if proj is None:
        return _err(404, "not_found", "projeto não encontrado")
    try:
        return {"worktrees": [w.to_dict() for w in wt.list_worktrees(proj.path)]}
    except wt.WorktreeError as e:
        return _wt_err(e)


@router.post("/projects/{project_id}/worktrees", status_code=201, dependencies=[Depends(require_local_write)])
def create_project_worktree(project_id: str, body: WorktreeIn, reg: ProjectRegistry = Depends(get_registry)):
    proj = reg.get(project_id)
    if proj is None:
        return _err(404, "not_found", "projeto não encontrado")
    try:
        return wt.create_worktree(proj.path, proj.name, body.branch).to_dict()
    except wt.WorktreeError as e:
        return _wt_err(e)


@router.delete("/projects/{project_id}/worktrees/{worktree_id}", dependencies=[Depends(require_local_write)])
def delete_project_worktree(project_id: str, worktree_id: str, confirm: bool = False, force: bool = False,
                            reg: ProjectRegistry = Depends(get_registry),
                            mgr: TerminalManager = Depends(get_manager)):
    proj = reg.get(project_id)
    if proj is None:
        return _err(404, "not_found", "projeto não encontrado")
    try:
        wt.delete_worktree(proj.path, worktree_id, confirm=confirm, force=force)
    except wt.WorktreeError as e:
        return _wt_err(e)
    for s in mgr.list():  # sessions living inside the removed worktree are pointless now
        if s.worktree_id == worktree_id:
            mgr.close(s.id, "worktree_removed")
    return {"removed": True}


# ------------------------------------------------------------------ profiles
@router.get("/profiles", dependencies=[Depends(require_localhost)])
def list_profiles(profiles: dict[str, Profile] = Depends(get_profiles)):
    return {"profiles": [p.describe() for p in profiles.values()]}


# ------------------------------------------------------------------ sessions
class SessionIn(BaseModel):
    project: str
    profile: str = "shell"
    cols: int = Field(default=80, ge=1, le=500)
    rows: int = Field(default=24, ge=1, le=500)
    worktree_id: str | None = Field(default=None, max_length=64)


@router.post("/sessions", status_code=201, dependencies=[Depends(require_local_write)])
def create_session(body: SessionIn, mgr: TerminalManager = Depends(get_manager),
                   reg: ProjectRegistry = Depends(get_registry),
                   profiles: dict[str, Profile] = Depends(get_profiles)):
    if not terminals_enabled():
        return _terminals_disabled()
    proj = reg.get(body.project)
    if proj is None:
        return _err(404, "project_not_found", "projeto não encontrado")
    prof = profiles.get(body.profile)
    if prof is None:
        return _err(404, "profile_not_found", "perfil não encontrado")
    cwd = None
    if body.worktree_id:
        try:
            cwd = wt.get_worktree(proj.path, body.worktree_id).path
        except wt.WorktreeError as e:
            return _wt_err(e)
    try:
        s = mgr.create(proj, prof, cols=body.cols, rows=body.rows, cwd=cwd, worktree_id=body.worktree_id)
    except ProfileUnavailable as e:
        return _err(422, "profile_unavailable", str(e), "instale a CLI ou abra o perfil 'shell'")
    except SessionLimitError as e:
        return _err(429, "session_limit", str(e), "encerre uma sessão antes de abrir outra")
    except (FileNotFoundError, ProfileError) as e:
        return _err(422, "cannot_start", str(e))
    except Exception as e:  # backend failure (pywinpty missing, spawn error)
        audit.warning("session_open_failed project=%s profile=%s error=%s", proj.id, prof.id,
                      type(e).__name__)
        return _err(500, "spawn_failed", "não foi possível iniciar o terminal", type(e).__name__)
    return {"session_id": s.id, "ws_url": f"/api/sessions/{s.id}/ws", "session": s.to_dict()}


@router.get("/sessions", dependencies=[Depends(require_local_write)])
def list_sessions(mgr: TerminalManager = Depends(get_manager)):
    if not terminals_enabled():
        return _terminals_disabled()
    return {"sessions": [s.to_dict() for s in mgr.list()]}


@router.delete("/sessions/{session_id}", dependencies=[Depends(require_local_write)])
def delete_session(session_id: str, mgr: TerminalManager = Depends(get_manager)):
    if not terminals_enabled():
        return _terminals_disabled()
    if not mgr.close(session_id, "user"):
        return _err(404, "not_found", "sessão não encontrada")
    return {"closed": True}


# ------------------------------------------------------------------ websocket
def _ws_authorized(ws: WebSocket) -> str | None:
    """Return the matched subprotocol (`tok.<token>`) if ALL checks pass, else None."""
    if not terminals_enabled():
        return None
    client = ws.client
    if not client or client.host not in {"127.0.0.1", "::1"}:
        return None
    host_header = ws.headers.get("host", "")
    hostname = urlsplit("//" + host_header).hostname or ""
    if not remote_allowed() and hostname.lower() not in LOOPBACK_HOSTS:  # DNS-rebinding guard
        return None
    origin = ws.headers.get("origin")
    if not origin:
        return None
    o = urlsplit(origin)
    if o.scheme not in ("http", "https") or o.netloc != host_header:
        return None
    expected = "tok." + get_or_create_local_token()
    for proto in ws.scope.get("subprotocols", []):
        if secrets.compare_digest(proto.encode(), expected.encode()):
            return proto
    return None


@router.websocket("/sessions/{session_id}/ws")
async def session_ws(ws: WebSocket, session_id: str, mgr: TerminalManager = Depends(get_manager)):
    proto = _ws_authorized(ws)
    if proto is None:
        audit.warning("ws_rejected client=%s", ws.client.host if ws.client else "?")
        await ws.close(code=WS_CLOSE_FORBIDDEN)
        return
    try:
        session = mgr.get(session_id)
    except SessionNotFound:
        await ws.close(code=WS_CLOSE_NOT_FOUND)
        return
    await ws.accept(subprotocol=proto)
    loop = asyncio.get_running_loop()
    sub, replay = mgr.subscribe(session_id, loop)
    audit.info("ws_attach session=%s", session_id)

    async def tx() -> None:
        await ws.send_text(json.dumps({"t": "replay", "bytes": len(replay)}))
        if replay:
            await ws.send_bytes(replay)
        await ws.send_text(json.dumps({"t": "state", "v": session.state}))
        while True:
            data = await sub.queue.get()
            if data is None:
                break
            await ws.send_bytes(data)
        if session.state == "ended":
            await ws.send_text(json.dumps({"t": "state", "v": "ended", "code": session.exit_code}))
            await ws.close(code=1000)

    def handle_text(raw: str) -> None:
        try:
            j = json.loads(raw)
        except ValueError:
            return
        if not isinstance(j, dict):
            return
        t = j.get("t")
        if t == "in" and isinstance(j.get("d"), str):
            mgr.write(session_id, j["d"])
        elif t in ("resize", "rs"):
            try:
                mgr.resize(session_id, int(j["rows"]), int(j["cols"]))
            except (KeyError, TypeError, ValueError):
                return

    async def rx() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                if len(msg["bytes"]) <= MAX_WS_MESSAGE:
                    mgr.write(session_id, msg["bytes"])
            elif msg.get("text") is not None and len(msg["text"]) <= MAX_WS_MESSAGE:
                handle_text(msg["text"])

    t_tx, t_rx = asyncio.create_task(tx()), asyncio.create_task(rx())
    try:
        await asyncio.wait({t_tx, t_rx}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pass  # server shutdown / harness teardown: fall through to cleanup (we are returning anyway)
    finally:
        for t in (t_tx, t_rx):
            t.cancel()
        mgr.unsubscribe(session_id, sub)  # synchronous, so it always runs
        audit.info("ws_detach session=%s", session_id)
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.gather(t_tx, t_rx, return_exceptions=True)
        if ws.application_state != WebSocketState.DISCONNECTED:
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await ws.close()
