"""ANA-174: diff gate for the implementer. Pure scope check + a thin git wrapper (local git, no network).

`verify_diff(changed, allowed)` -> (ok, violations). `allowed` entries are path prefixes or globs relative to the
repo root. Enabled by ANAMNESIA_DIFF_GATE=1 (the orchestrator does not call it unless the flag is on).
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import PurePosixPath


def diff_gate_enabled() -> bool:
    return os.environ.get("ANAMNESIA_DIFF_GATE", "").strip().lower() in ("1", "true", "on", "yes")


def _norm(p: str) -> str:
    s = str(p).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def _in_scope(path: str, allowed: list[str]) -> bool:
    p = _norm(path)
    if p.startswith("/") or ":" in p.split("/")[0] or ".." in PurePosixPath(p).parts:
        return False
    for a in allowed:
        a = _norm(a)
        if fnmatch.fnmatchcase(p, a) or p == a.rstrip("/") or p.startswith(a.rstrip("/") + "/"):
            return True
    return False


def verify_diff(changed_paths: list[str], allowed_scope: list[str]) -> tuple[bool, list[str]]:
    bad = [p for p in changed_paths if not _in_scope(p, allowed_scope)]
    return (not bad), bad


def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=60, check=False)


def changed_paths(worktree) -> list[str]:
    """Tracked changes + untracked files, relative to the worktree root."""
    out: list[str] = []
    for args in (("diff", "--name-only", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
        r = _git(worktree, *args)
        if r.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
        out += [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return sorted(set(out))


def is_git_worktree(path) -> bool:
    try:
        r = _git(path, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def snapshot(worktree) -> set:
    """Paths already dirty BEFORE a step (the user's own work). `.anamnesia/` (our run dirs) is never judged."""
    return {p for p in changed_paths(worktree) if not _norm(p).startswith(".anamnesia/")}


def gate_since(worktree, allowed_scope: list[str], baseline, *, revert_on_fail: bool = True) -> dict:
    """Judge only what changed AFTER `baseline` (so pre-existing user edits are never judged nor reverted).
    Violations are reverted one path at a time: tracked -> `git checkout HEAD -- p`; untracked file -> removed.
    Known limit: a file already dirty in the baseline and edited further is not detected."""
    base = set(baseline or ())
    paths = [p for p in changed_paths(worktree) if p not in base and not _norm(p).startswith(".anamnesia/")]
    ok, bad = verify_diff(paths, allowed_scope)
    res = {"ok": ok, "changed": paths, "violations": bad, "reverted": False}
    if not ok and revert_on_fail:
        root = os.path.realpath(worktree)
        for p in bad:
            tracked = _git(worktree, "ls-files", "--error-unmatch", "--", p).returncode == 0
            if tracked:
                _git(worktree, "checkout", "HEAD", "--", p)
            else:
                target = os.path.realpath(os.path.join(worktree, p))
                if target.startswith(root + os.sep) and os.path.isfile(target):
                    os.remove(target)
        left = {p for p in changed_paths(worktree)}
        res["reverted"] = not any(p in left for p in bad)
    return res


def gate_worktree(worktree, allowed_scope: list[str], *, revert_on_fail: bool = True) -> dict:
    """Check a worktree; on violation restore tracked files and remove untracked ones (automatic revert)."""
    paths = changed_paths(worktree)
    ok, bad = verify_diff(paths, allowed_scope)
    res = {"ok": ok, "changed": paths, "violations": bad, "reverted": False}
    if not ok and revert_on_fail:
        _git(worktree, "checkout", "--", ".")
        _git(worktree, "clean", "-fd")
        res["reverted"] = not changed_paths(worktree)
    return res
