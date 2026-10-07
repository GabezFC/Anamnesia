"""Run directory `.anamnesia/runs/<run_id>/` under the project path.

Layout:  task.md · events.jsonl · summary.json · <step_id>/result.md · <step_id>/status.json
All paths go through `safe_join`, which rejects absolute parts, `..` and symlink escapes.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
STEP_ID_RE = re.compile(r"^[a-z]+(-\d{1,3})?$")
STATES = ("planned", "running", "done", "failed", "cancelled")
TERMINAL = frozenset({"done", "failed", "cancelled"})
TRANSITIONS = {
    "planned": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"done", "failed", "cancelled"}),
    "done": frozenset(), "failed": frozenset(), "cancelled": frozenset(),
}


class RunError(ValueError):
    pass


class InvalidTransition(RunError):
    pass


def safe_join(base, *parts) -> Path:
    """base/part/... guaranteed to stay under base (after resolving symlinks). Raises RunError otherwise."""
    root = Path(os.path.realpath(base))
    cur = root
    for part in parts:
        s = str(part)
        if not s or s in (".", "..") or "\x00" in s or Path(s).is_absolute() or re.match(r"^[A-Za-z]:", s) \
                or re.search(r"[\\/]", s):
            raise RunError(f"unsafe path component: {s!r}")
        cur = cur / s
    real = Path(os.path.realpath(cur))
    try:
        real.relative_to(root)
    except ValueError:
        raise RunError(f"path escapes base directory: {parts!r}") from None
    return real


def check_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise RunError(f"invalid run id: {run_id!r}")
    return run_id


def new_run_id() -> str:
    return time.strftime("r%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)


def project_root(project_path) -> Path:
    p = Path(os.path.realpath(str(project_path)))
    if not p.is_dir():
        raise RunError(f"project path is not a directory: {project_path}")
    return p


def runs_root(project_path) -> Path:
    return safe_join(project_root(project_path), ".anamnesia", "runs")


class Run:
    """One run on disk. Thread-safe state + event log."""

    def __init__(self, project_path, run_id: str):
        self.project = project_root(project_path)
        self.run_id = check_run_id(run_id)
        self.dir = safe_join(self.project, ".anamnesia", "runs", self.run_id)
        self._lock = threading.RLock()
        self.summary: dict = {}
        self.cancel_event = threading.Event()

    # ---- creation / loading
    @classmethod
    def create(cls, project_path, task: str, preset: str, run_id: str | None = None, **meta) -> "Run":
        r = cls(project_path, new_run_id() if run_id is None else run_id)
        if r.dir.exists():
            raise RunError(f"run already exists: {r.run_id}")
        r.dir.mkdir(parents=True)
        (r.dir / "task.md").write_text(task.rstrip() + "\n", encoding="utf-8")
        now = time.time()
        r.summary = {"run_id": r.run_id, "state": "planned", "preset": preset, "reason": None,
                     "project_path": str(r.project),
                     "created_at": now, "updated_at": now, "steps": [], "warnings": [], **meta}
        r.write_summary()
        r.event("created", preset=preset)
        return r

    @classmethod
    def load(cls, project_path, run_id: str) -> "Run":
        r = cls(project_path, run_id)
        f = r.dir / "summary.json"
        if not f.is_file():
            raise RunError(f"run not found: {run_id}")
        r.summary = json.loads(f.read_text(encoding="utf-8"))
        return r

    # ---- state machine
    @property
    def state(self) -> str:
        return self.summary["state"]

    def transition(self, new: str, reason: str | None = None) -> None:
        with self._lock:
            if new not in STATES:
                raise InvalidTransition(f"unknown state {new!r}")
            if new not in TRANSITIONS[self.state]:
                raise InvalidTransition(f"{self.state} -> {new} not allowed")
            old = self.state
            self.summary["state"] = new
            self.summary["reason"] = reason
            self.write_summary()
            self.event("state", old=old, new=new, reason=reason)

    # ---- files
    def write_summary(self) -> None:
        with self._lock:
            self.summary["updated_at"] = time.time()
            tmp = self.dir / "summary.json.tmp"
            tmp.write_text(json.dumps(self.summary, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.dir / "summary.json")

    def event(self, type_: str, **data) -> None:
        with self._lock:
            rec = {"ts": time.time(), "type": type_, **data}
            with open(self.dir / "events.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def events(self) -> list:
        f = self.dir / "events.jsonl"
        if not f.is_file():
            return []
        return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def task_text(self) -> str:
        return (self.dir / "task.md").read_text(encoding="utf-8")

    def step_dir(self, step_id: str, create: bool = True) -> Path:
        if not STEP_ID_RE.match(step_id):
            raise RunError(f"invalid step id: {step_id!r}")
        d = safe_join(self.dir, step_id)
        if create:
            d.mkdir(exist_ok=True)
        return d

    def result_path(self, step_id: str) -> Path:
        return self.step_dir(step_id) / "result.md"

    def status_path(self, step_id: str) -> Path:
        return self.step_dir(step_id) / "status.json"

    def read_result(self, step_id: str) -> str | None:
        f = self.result_path(step_id)
        return f.read_text(encoding="utf-8") if f.is_file() else None

    def read_status(self, step_id: str) -> dict | None:
        f = self.status_path(step_id)
        if not f.is_file():
            return None
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def list_runs(project_path) -> list:
    """Summaries of every run under the project, newest first. Unreadable entries are skipped."""
    try:
        root = runs_root(project_path)
    except RunError:
        return []
    out = []
    if root.is_dir():
        for d in root.iterdir():
            f = d / "summary.json"
            if RUN_ID_RE.match(d.name) and f.is_file():
                try:
                    out.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
    return sorted(out, key=lambda s: s.get("created_at", 0), reverse=True)
