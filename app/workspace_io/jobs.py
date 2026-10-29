"""Tarefas longas em segundo plano: progresso, resultado, erros e cancelamento COOPERATIVO.

Cancelar nunca mata a thread: o trabalho verifica `job.cancelled` entre unidades atômicas (um arquivo, uma nota)
e para limpo; o que já foi gravado fica consistente (gravações atômicas) e a repetição da tarefa é idempotente.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_JOBS = 40
RESULT_TTL_S = 3600
QUEUED, RUNNING, DONE, FAILED, CANCELLED = "queued", "running", "done", "failed", "cancelled"
FINAL = frozenset({DONE, FAILED, CANCELLED})


class Cancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    project_id: str | None
    label: str = ""
    state: str = QUEUED
    phase: str = ""
    done: int = 0
    total: int = 0
    result: dict | None = None
    errors: list[dict] = field(default_factory=list)
    error: str | None = None
    exc: BaseException | None = field(default=None, repr=False)   # exceção original (a API traduz erros de validação)
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    cancel_requested: bool = False
    artifact: dict | None = None            # {filename, media_type, data(bytes)} — baixado via /download
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- chamado pelo trabalho -------------------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self.cancel_requested

    def check(self) -> None:
        if self.cancel_requested:
            raise Cancelled()

    def progress(self, done: int | None = None, total: int | None = None, phase: str | None = None) -> None:
        with self._lock:
            if done is not None:
                self.done = done
            if total is not None:
                self.total = total
            if phase is not None:
                self.phase = phase

    def add_error(self, item: str, message: str) -> None:
        with self._lock:
            if len(self.errors) < 200:
                self.errors.append({"item": item, "message": message})

    def to_dict(self, with_result: bool = True) -> dict:
        with self._lock:
            d = {"id": self.id, "kind": self.kind, "project_id": self.project_id, "label": self.label,
                 "state": self.state, "phase": self.phase, "done": self.done, "total": self.total,
                 "percent": (round(100 * self.done / self.total) if self.total else (100 if self.state == DONE else 0)),
                 "cancel_requested": self.cancel_requested, "errors": list(self.errors), "error": self.error,
                 "created_at": self.created_at, "started_at": self.started_at, "finished_at": self.finished_at,
                 "has_download": bool(self.artifact)}
            if with_result:
                d["result"] = self.result
            return d


class JobManager:
    def __init__(self, max_jobs: int = MAX_JOBS):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self.max_jobs = max_jobs

    def _gc(self) -> None:
        now = time.time()
        for jid in [j.id for j in self._jobs.values() if j.state in FINAL and j.finished_at and now - j.finished_at > RESULT_TTL_S]:
            self._jobs.pop(jid, None)
        while len(self._jobs) > self.max_jobs:
            old = next((j for j in sorted(self._jobs.values(), key=lambda j: j.created_at) if j.state in FINAL), None)
            if old is None:
                break
            self._jobs.pop(old.id, None)

    def active(self, kind: str, project_id: str | None) -> Job | None:
        with self._lock:
            return next((j for j in self._jobs.values()
                         if j.kind == kind and j.project_id == project_id and j.state not in FINAL), None)

    def submit(self, kind: str, project_id: str | None, label: str, fn: Callable[[Job], dict | None],
               *, synchronous: bool = False) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, project_id=project_id, label=label)
        with self._lock:
            self._gc()
            self._jobs[job.id] = job

        def run() -> None:
            job.state, job.started_at = RUNNING, time.time()
            try:
                job.result = fn(job)
                job.state = CANCELLED if job.cancel_requested else DONE
            except Cancelled:
                job.state = CANCELLED
            except Exception as exc:  # noqa: BLE001 - a UI precisa de um motivo, nunca de um 500 mudo
                job.state, job.error, job.exc = FAILED, f"{type(exc).__name__}: {exc}", exc
            finally:
                job.finished_at = time.time()

        if synchronous:
            run()
        else:
            threading.Thread(target=run, name=f"wsio-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is not None and job.state not in FINAL:
            job.cancel_requested = True
            if job.state == QUEUED:
                job.state = CANCELLED
        return job


_manager: JobManager | None = None
_mlock = threading.Lock()


def get_jobs() -> JobManager:
    global _manager
    with _mlock:
        if _manager is None:
            _manager = JobManager()
        return _manager
