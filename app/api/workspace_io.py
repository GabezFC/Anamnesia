"""API da Central de Importação, Exportação e Inicialização (/api/workspace/io/*).

Prévia (dry_run=true) é síncrona e não grava nada; a aplicação roda como tarefa em segundo plano
(progresso em GET /jobs/{id}, cancelamento seguro em POST /jobs/{id}/cancel, arquivo exportado em /download).
Escritas e downloads exigem `require_local_write` (loopback + Origin + X-MG-Token), como o resto do workspace.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.api.workspace import get_registry
from app.services.security import require_local_write, require_localhost
from app.terminals.projects import ProjectRegistry
from app.workspace_io import tasks
from app.workspace_io.jobs import FINAL, Cancelled, JobManager, get_jobs

router = APIRouter(prefix="/api/workspace/io")
log = logging.getLogger("anamnesia.workspace_io")


def _err(status: int, code: str, message: str, hint: str = "") -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "hint": hint}}, status_code=status)


def _wio(e: tasks.WorkspaceIOError) -> JSONResponse:
    return _err(e.status, e.code, e.message, e.hint)


class InitIn(BaseModel):
    project_id: str
    dry_run: bool = True
    install_project_files: bool = False
    summary_note: bool = True


class ImportFile(BaseModel):
    name: str = Field(max_length=300)
    content: str


class ImportIn(BaseModel):
    project_id: str | None = None
    dry_run: bool = True
    source: Literal["upload", "path"] = "upload"
    files: list[ImportFile] = Field(default_factory=list)
    path: str = Field("", max_length=4096)


class ExportIn(BaseModel):
    project_id: str | None = None
    kind: Literal["memories", "context", "metadata", "index", "report", "metrics"]
    format: Literal["json", "md", "csv"] = "json"
    scope: Literal["project", "all"] = "project"
    dry_run: bool = True


def _proj(reg: ProjectRegistry, project_id: str | None, required: bool):
    if not project_id:
        if required:
            raise tasks.WorkspaceIOError("project_required", "selecione um projeto", status=422)
        return None
    p = reg.get(project_id)
    if p is None:
        raise tasks.WorkspaceIOError("not_found", "projeto não encontrado", status=404)
    return p


def _run(jm: JobManager, kind: str, project_id: str | None, label: str, dry_run: bool, fn):
    """Prévia: síncrona, devolve 200 {job}. Aplicação: 202 e thread. Uma tarefa por (tipo, projeto)."""
    if not dry_run:
        busy = jm.active(kind, project_id)
        if busy is not None:
            return _err(409, "job_running", "já existe uma tarefa deste tipo em andamento para o projeto", busy.id)
    if not dry_run:
        inner = fn

        def fn(job):  # noqa: F811 - registra a operação APLICADA no histórico persistente (sucesso, falha ou cancelamento)
            state, summary = "failed", ""
            try:
                res = inner(job)
                state = "cancelled" if job.cancel_requested else "done"
                summary = tasks.summarize_result(kind, res)
                return res
            except Cancelled:
                state = "cancelled"
                raise
            except Exception as exc:
                summary = f"{type(exc).__name__}: {exc}"[:300]
                raise
            finally:
                tasks.record_history({"id": job.id, "kind": kind, "project_id": project_id, "label": label,
                                      "state": state, "summary": summary, "errors": len(job.errors),
                                      "at": time.time()})

    job = jm.submit(kind, project_id, label, fn, synchronous=dry_run)
    if dry_run:
        if job.state == "failed":
            if isinstance(job.exc, tasks.WorkspaceIOError):
                return _wio(job.exc)
            return _err(500, "preview_failed", job.error or "falha na prévia")
        return {"job": job.to_dict()}
    return JSONResponse({"job": job.to_dict(with_result=False)}, status_code=202)


@router.get("/capabilities", dependencies=[Depends(require_localhost)])
def capabilities():
    return {"docker": tasks.in_docker(), "import_formats": [".md", ".markdown", ".json"],
            "export_kinds": list(tasks.EXPORT_KINDS), "export_formats": list(tasks.EXPORT_FORMATS),
            "limits": {"import_items": tasks.MAX_IMPORT_ITEMS, "import_bytes": tasks.MAX_IMPORT_BYTES,
                       "import_file_bytes": tasks.MAX_IMPORT_FILE_BYTES},
            "secrets_policy": "segredos nunca são exportados nem indexados"}


@router.get("/status", dependencies=[Depends(require_localhost)])
def status(project_id: str | None = None, reg: ProjectRegistry = Depends(get_registry)):
    """Identificação, disponibilidade da pasta e índice REAL do projeto (nada inventado)."""
    if not project_id:
        return _err(422, "project_required", "selecione um projeto")
    p = reg.get(project_id)
    if p is None:
        return _err(404, "not_found", "projeto não encontrado")
    avail = tasks.project_availability(p.path)
    return {"project": {"id": p.id, "name": p.name, "path": p.display_path, "container_path": p.path,
                        "host_path": p.host_path}, "docker": tasks.in_docker(),
            "availability": avail, "index": tasks.index_status(p.id),
            "memories": tasks.memory_count(p.name)}


@router.get("/history", dependencies=[Depends(require_localhost)])
def history(project_id: str | None = None, limit: int = 15):
    """Últimas operações APLICADAS (persistidas em disco; prévias não entram)."""
    return {"history": tasks.read_history(max(1, min(limit, 100)), project_id)}


@router.post("/initialize", dependencies=[Depends(require_local_write)])
def initialize(body: InitIn, reg: ProjectRegistry = Depends(get_registry), jm: JobManager = Depends(get_jobs)):
    try:
        proj = _proj(reg, body.project_id, True)
        tasks.ensure_project_dir(proj.path)
    except tasks.WorkspaceIOError as e:
        return _wio(e)
    return _run(jm, "initialize", proj.id, f"Inicializar {proj.name}", body.dry_run,
                lambda job: tasks.run_initialize(proj, job, apply=not body.dry_run,
                                                 install_project_files=body.install_project_files,
                                                 summary_note=body.summary_note))


@router.post("/import", dependencies=[Depends(require_local_write)])
def import_memories(body: ImportIn, reg: ProjectRegistry = Depends(get_registry), jm: JobManager = Depends(get_jobs)):
    try:
        proj = _proj(reg, body.project_id, body.source == "path")
        root = tasks.ensure_project_dir(proj.path) if body.source == "path" else None
        if body.source == "upload" and not body.files:
            return _err(422, "no_files", "nenhum arquivo enviado", "escolha arquivos .md ou .json")
        if body.source == "path":
            from app.terminals.projects import PathEscapeError, safe_join
            try:
                target = safe_join(root, body.path or "")
            except PathEscapeError as exc:
                raise tasks.WorkspaceIOError("path_escape", "caminho fora do projeto", status=403) from exc
            if not target.exists():
                raise tasks.WorkspaceIOError("not_found", f"caminho não encontrado no projeto: {body.path or '.'}",
                                             "confira o caminho relativo à raiz do projeto", 404)
        uploaded = tasks.gather_import_items([f.model_dump() for f in body.files]) if body.source == "upload" else None
    except tasks.WorkspaceIOError as e:
        return _wio(e)

    def work(job):
        files = uploaded if uploaded is not None else tasks.gather_import_path(root, body.path, job)
        return tasks.run_import(files, job, apply=not body.dry_run, project_name=proj.name if proj else None)

    return _run(jm, "import", proj.id if proj else None, "Importar memórias", body.dry_run, work)


@router.post("/export", dependencies=[Depends(require_local_write)])
def export(body: ExportIn, reg: ProjectRegistry = Depends(get_registry), jm: JobManager = Depends(get_jobs)):
    try:
        proj = _proj(reg, body.project_id, body.kind == "index" or body.scope == "project")
    except tasks.WorkspaceIOError as e:
        return _wio(e)
    if body.kind == "index" and proj is not None and not tasks.load_index(proj.id)["files"]:
        return _wio(tasks.WorkspaceIOError("no_index", "projeto ainda sem índice",
                                           "rode Inicializar projeto antes de exportar o índice", 409))
    return _run(jm, "export", proj.id if proj else None, f"Exportar {body.kind}", body.dry_run,
                lambda job: tasks.run_export(body.kind, body.format, job, apply=not body.dry_run, project=proj, scope=body.scope))


@router.get("/jobs", dependencies=[Depends(require_localhost)])
def list_jobs(jm: JobManager = Depends(get_jobs)):
    return {"jobs": [j.to_dict(with_result=False) for j in jm.list()]}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_localhost)])
def get_job(job_id: str, jm: JobManager = Depends(get_jobs)):
    j = jm.get(job_id)
    return {"job": j.to_dict()} if j else _err(404, "not_found", "tarefa não encontrada")


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(require_local_write)])
def cancel_job(job_id: str, jm: JobManager = Depends(get_jobs)):
    j = jm.cancel(job_id)
    return {"job": j.to_dict(with_result=False)} if j else _err(404, "not_found", "tarefa não encontrada")


@router.get("/jobs/{job_id}/download", dependencies=[Depends(require_local_write)])
def download(job_id: str, jm: JobManager = Depends(get_jobs)):
    j = jm.get(job_id)
    if j is None or not j.artifact:
        return _err(404, "not_found", "nada para baixar nesta tarefa")
    a = j.artifact
    return Response(a["data"], media_type=a["media_type"],
                    headers={"Content-Disposition": f'attachment; filename="{a["filename"]}"', "Cache-Control": "no-store"})
