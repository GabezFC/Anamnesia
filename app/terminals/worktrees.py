"""Optional git worktrees per project (T10.7). All git calls: argv list, no shell, timeouts.

Managed worktrees live in `<project>/../.anamnesia-worktrees/<project>-<branch>` (branch `/` -> `-`).
Only worktrees under that directory can be deleted through this module; the primary worktree never.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

GIT_TIMEOUT = 30
WORKTREES_DIRNAME = ".anamnesia-worktrees"
# Starts alphanumeric (no option injection), no "..", segments separated by single "/".
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,63}){0,3}$")


class WorktreeError(ValueError):
    """Base: message is safe to show to the user. `code` maps to an API error code."""

    code = "worktree_error"


class NotAGitRepo(WorktreeError):
    code = "not_a_git_repo"


class InvalidBranch(WorktreeError):
    code = "invalid_branch"


class WorktreeNotFound(WorktreeError):
    code = "not_found"


class WorktreeConflict(WorktreeError):
    code = "conflict"


class WorktreeDirty(WorktreeError):
    code = "dirty"


class WorktreeForbidden(WorktreeError):
    code = "forbidden"


@dataclass(frozen=True)
class Worktree:
    id: str
    path: str
    branch: str | None
    head: str | None
    primary: bool
    managed: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _norm(p: str | os.PathLike) -> str:
    return os.path.normcase(os.path.realpath(p))


def worktree_id(path: str | os.PathLike) -> str:
    return hashlib.sha1(_norm(path).encode("utf-8")).hexdigest()[:12]


def validate_branch(branch: str) -> str:
    if not isinstance(branch, str) or not BRANCH_RE.fullmatch(branch):
        raise InvalidBranch("nome de branch inválido (letras, números, . _ - e / entre segmentos)")
    if ".." in branch or branch.endswith((".", ".lock")) or "//" in branch or "/." in branch:
        raise InvalidBranch("nome de branch inválido")
    return branch


def _git(cwd: str, *args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT",
                            "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME"}}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env, shell=False, check=False)
    except FileNotFoundError as e:
        raise WorktreeError("git não encontrado no PATH") from e
    except subprocess.TimeoutExpired as e:
        raise WorktreeError("git excedeu o tempo limite") from e


def managed_root(project_path: str) -> Path:
    return Path(os.path.realpath(project_path)).parent / WORKTREES_DIRNAME


def _is_managed(project_path: str, path: str) -> bool:
    root = os.path.normcase(str(managed_root(project_path)))
    p = _norm(path)
    return p.startswith(root + os.sep)


def list_worktrees(project_path: str) -> list[Worktree]:
    cp = _git(project_path, "worktree", "list", "--porcelain")
    if cp.returncode != 0:
        raise NotAGitRepo("o projeto não é um repositório git")
    entries: list[dict] = []
    cur: dict = {}
    for line in cp.stdout.splitlines() + [""]:
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val
    out: list[Worktree] = []
    for i, e in enumerate(entries):
        path = e.get("worktree", "")
        if not path or "prunable" in e:
            continue
        branch = e.get("branch")
        if branch and branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/"):]
        out.append(Worktree(worktree_id(path), os.path.realpath(path), branch, (e.get("HEAD") or "")[:12] or None,
                            primary=(i == 0), managed=(i != 0 and _is_managed(project_path, path))))
    return out


def get_worktree(project_path: str, wt_id: str) -> Worktree:
    for w in list_worktrees(project_path):
        if w.id == wt_id:
            if not os.path.isdir(w.path):
                raise WorktreeNotFound("worktree não existe mais no disco")
            return w
    raise WorktreeNotFound("worktree não encontrado")


def create_worktree(project_path: str, project_name: str, branch: str) -> Worktree:
    validate_branch(branch)
    existing = list_worktrees(project_path)  # also proves it is a git repo
    if any(w.branch == branch for w in existing):
        raise WorktreeConflict("essa branch já está em uso por outro worktree")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-.") or "project"
    target = managed_root(project_path) / f"{slug}-{branch.replace('/', '-')}"
    if target.exists():
        raise WorktreeConflict("o diretório do worktree já existe")
    target.parent.mkdir(parents=True, exist_ok=True)
    exists = _git(project_path, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
    args = ["worktree", "add"] + ([str(target), branch] if exists else ["-b", branch, str(target)])
    cp = _git(project_path, *args, timeout=120)
    if cp.returncode != 0:
        raise WorktreeError("git worktree add falhou: " + (cp.stderr.strip().splitlines() or ["erro"])[-1][:300])
    wid = worktree_id(target)
    return get_worktree(project_path, wid)


def delete_worktree(project_path: str, wt_id: str, confirm: bool = False, force: bool = False) -> None:
    if not confirm:
        raise WorktreeForbidden("confirmação obrigatória (confirm=true)")
    w = get_worktree(project_path, wt_id)
    if w.primary:
        raise WorktreeForbidden("o worktree principal nunca é removido")
    if not w.managed:
        raise WorktreeForbidden("só worktrees criados pela Anamnésia podem ser removidos aqui")
    if not force:
        st = _git(w.path, "status", "--porcelain")
        if st.returncode != 0:
            raise WorktreeError("não foi possível verificar o estado do worktree")
        if st.stdout.strip():
            raise WorktreeDirty("o worktree tem alterações não commitadas (use force=true para descartar)")
    cp = _git(project_path, "worktree", "remove", *(["--force"] if force else []), w.path, timeout=120)
    if cp.returncode != 0:
        raise WorktreeError("git worktree remove falhou: " + (cp.stderr.strip().splitlines() or ["erro"])[-1][:300])
    if os.path.isdir(w.path) and _is_managed(project_path, w.path):  # leftover untracked/ignored files
        shutil.rmtree(w.path, ignore_errors=True)
    _git(project_path, "worktree", "prune")
