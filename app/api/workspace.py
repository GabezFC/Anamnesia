"""Workspace API: projects, read-only file explorer, inicialização de projeto e JEV.

Os endpoints de sessão interativa de terminal (REST /api/sessions*, /api/profiles, worktrees e o
WebSocket /api/sessions/{id}/ws) foram REMOVIDOS com a UI de terminal (Fase 10 descontinuada).
O PTY continua só como launcher interno não visual (app/orchestration/pty_launcher.py, usado pelo delegate
no modo ANAMNESIA_DELEGATE_LAUNCHER=terminal). NENHUMA rota deste módulo depende do manager PTY.

Security: every state-changing REST call (and the sensitive reads) uses `require_local_write`."""
from __future__ import annotations

import logging
import os
import threading

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.orchestration import pty_launcher
from app.services.security import require_local_write, require_localhost
from app.services import project_guard
from app.terminals import path_map
from app.terminals.projects import (PathEscapeError, ProjectError, ProjectRegistry, SecretFileError,
                                    list_dir, read_file, search_content, search_names)

router = APIRouter(prefix="/api")
audit = logging.getLogger("anamnesia.terminals.audit")


# ------------------------------------------------------------------ deps
_registry: ProjectRegistry | None = None
_init_lock = threading.Lock()


def get_registry() -> ProjectRegistry:
    global _registry
    with _init_lock:
        if _registry is None:
            _registry = ProjectRegistry()
        return _registry


def _err(status: int, code: str, message: str, hint: str = "") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "hint": hint}}, status_code=status)


# ------------------------------------------------------------------ projects
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=4096)


@router.get("/projects", dependencies=[Depends(require_localhost)])
def list_projects(reg: ProjectRegistry = Depends(get_registry)):
    return {"projects": [p.to_dict() for p in reg.list()]}


@router.get("/workspace/roots", dependencies=[Depends(require_localhost)])
def workspace_roots():
    """Raízes autorizadas host -> contêiner (ANAMNESIA_PATH_MAP). Sem segredos: só caminhos e flags."""
    roots = path_map.roots_info()
    return {"mapped": bool(roots), "docker": path_map._in_docker(), "roots": roots,
            "env": {"map": path_map.ENV_MAP, "host": "ANAMNESIA_PROJECTS_HOST"},
            "hint": "" if roots else ("Sem raízes mapeadas: o caminho é lido diretamente pelo processo (modo nativo)."
                                       if not path_map._in_docker() else path_map.RECREATE_HINT)}


_PATH_STATUS = {"path_not_mapped": 403, "path_escape": 403, "path_permission": 403,
                "path_not_found": 404, "path_invalid": 422}


def _path_err(e: path_map.PathMapError) -> JSONResponse:
    body = {"error": {"code": e.code, "message": e.message, "hint": e.hint, "roots": e.roots}}
    return JSONResponse(body, status_code=_PATH_STATUS.get(e.code, 422))


@router.post("/projects", status_code=201, dependencies=[Depends(require_local_write)])
def add_project(body: ProjectIn, reg: ProjectRegistry = Depends(get_registry)):
    try:
        tr = path_map.resolve_project_path(body.path)  # host -> contêiner (+ realpath dentro da raiz)
        project_guard.check_host(tr.host_path)  # ANA-026 também sobre o caminho do host
        project_guard.check(tr.container_path)  # HOME/.ssh/AppData/drive roots -> 403 (mode warn|off via env)
        return reg.add(body.name, body.path, translation=tr).to_dict()
    except project_guard.ProjectDenied as e:
        return _err(403, "project_root_denied", str(e),
                    "use um diretório de projeto; ou defina MG_PROJECT_ROOTS / ANAMNESIA_PROJECT_GUARD=warn")
    except path_map.PathMapError as e:
        return _path_err(e)
    except ProjectError as e:
        return _err(422, "invalid_project", str(e), "informe o caminho de um diretório existente")


@router.delete("/projects/{project_id}", dependencies=[Depends(require_local_write)])
def remove_project(project_id: str, purge_index: bool = False, reg: ProjectRegistry = Depends(get_registry)):
    """DESVINCULA o projeto (cadastro/seleção). NUNCA toca na pasta nem nos arquivos do projeto.

    `purge_index=true` (opt-in, confirmado na UI) também apaga o índice do Workspace deste projeto
    (`<data>/workspace_index/<id>.json`); memórias/notas compartilhadas e outros projetos não são afetados.
    Remoção repetida/id inexistente: 404 `not_found` (idempotente: nada muda).
    """
    if not reg.remove(project_id):
        return _err(404, "not_found", "projeto não encontrado (talvez já tenha sido removido)")
    # Sessões PTY do launcher interno (se o manager já existir; nunca é instanciado aqui). Arquivos intactos.
    pty_launcher.close_project_sessions(project_id)
    purged = False
    if purge_index:
        from app.workspace_io import tasks
        purged = tasks.purge_index(project_id)
    audit.info("project_removed id=%s purge_index=%s", project_id, purge_index)
    return {"removed": True, "id": project_id, "files_untouched": True, "index_purged": purged,
            "index_kept": not purge_index}


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


@router.get("/projects/{project_id}/file", dependencies=[Depends(require_local_write)])
def project_file(project_id: str, path: str,
                 reg: ProjectRegistry = Depends(get_registry)):
    """Pré-visualização somente leitura de um arquivo de texto (<= 200 KB; segredos bloqueados)."""
    proj = reg.get(project_id)
    if proj is None:
        return _err(404, "not_found", "projeto não encontrado")
    try:
        return read_file(proj.path, path)
    except PathEscapeError:
        return _err(403, "path_escape", "caminho fora do projeto")
    except SecretFileError as e:
        return _err(403, "secret_file", str(e))
    except (ProjectError, OSError):
        return _err(404, "not_found", "arquivo não encontrado")


# ------------------------------------------------------------------ initialize project (Anamnésia no projeto)
class InitializeIn(BaseModel):
    dry_run: bool = False


@router.post("/projects/{project_id}/initialize", dependencies=[Depends(require_local_write)])
def initialize_project(project_id: str, body: InitializeIn | None = None,
                       reg: ProjectRegistry = Depends(get_registry)):
    """Cria só os arquivos ausentes que ligam o projeto ao Anamnésia/Memory Gateway (manifesto em config/)."""
    from app.terminals import project_initializer as pi
    proj = reg.get(project_id)
    if proj is None:
        return _err(404, "not_found", "projeto não encontrado")
    try:
        rep = pi.initialize(proj.path, proj.name, dry_run=bool(body and body.dry_run))
    except pi.InitError as e:
        status = {"gateway_not_configured": 409, "project_not_writable": 403, "project_invalid": 404}.get(e.code, 500)
        return _err(status, e.code, e.message, e.hint)
    except Exception as e:  # nunca devolver o 500 genérico: a UI precisa de um motivo
        audit.warning("project_initialize_failed project=%s error=%s", proj.id, type(e).__name__)
        return _err(500, "initialize_failed", f"Falha inesperada ao inicializar: {type(e).__name__}: {e}",
                    "Veja os logs do Anamnésia (anamnesia.terminals.audit).")
    audit.info("project_initialize project=%s created=%d existing=%d failed=%d", proj.id, len(rep.created),
               len(rep.existing), len(rep.failed))
    return rep.to_dict()


# ------------------------------------------------------------------ JEV (configuração guiada; lógica em app/services/jev_setup.py)
class JevConfigIn(BaseModel):
    api_key: str | None = Field(None, max_length=2000)
    settings: dict = Field(default_factory=dict)


def _jev_gateway():
    from app.core.state import STATE
    return getattr(STATE, "gateway", None)


@router.get("/jev/status", dependencies=[Depends(require_local_write)])
def jev_status():
    from app.services import jev_setup
    gw = _jev_gateway()
    out = jev_setup.status(gw.db if gw else None)
    out["gateway_ready"] = gw is not None
    return out


@router.post("/jev/config", dependencies=[Depends(require_local_write)])
def jev_save_config(body: JevConfigIn):
    from app.services import jev_setup
    gw = _jev_gateway()
    try:
        res = jev_setup.save(body.settings, api_key=body.api_key, db=gw.db if gw else None)
        jev_setup.apply_to_gateway(gw)
    except jev_setup.JevSetupError as e:
        return _err(422, e.code, e.message, e.field or "")
    except ValueError as e:  # JevConfig.validate()
        return _err(422, "invalid_field", str(e))
    res["status"]["gateway_ready"] = gw is not None
    return res


@router.post("/jev/test", dependencies=[Depends(require_local_write)])
def jev_test_connection():
    from app.services import jev_setup
    gw = _jev_gateway()
    return jev_setup.test_connection(gw.db if gw else None)
