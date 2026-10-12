"""ANA-024: guard for every place the Gateway executes an external command (verifiers, terminal launchers).

Rules: allowlist by executable name (never a shell), cwd confined to allowed roots, hard timeout cap,
POSIX rlimits, and ONE audit record per decision (allowed / warned / denied) in logs/exec_audit.jsonl.

Modes (env `ANAMNESIA_EXEC_GUARD`, or the explicit `mode` argument):
  enforce  deny anything outside the allowlist / roots (default for verifiers)
  warn     allow but record `warn` (default for terminal launchers: profiles come from trusted config and
           a strict default could break local integrations)
  off      allow, still audited (rollback switch; the audit line is the minimum guarantee)
Extra allowed executables: `ANAMNESIA_EXEC_ALLOWLIST=name1,name2` (names without extension).
Only argv[0] and the argument COUNT are logged -- arguments may carry secrets.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

MODES = ("enforce", "warn", "off")
MAX_TIMEOUT_S = 900.0

DEFAULT_ALLOWLIST = frozenset({
    # test runners / toolchains used by verifiers
    "python", "python3", "py", "pytest", "node", "npm", "npx", "pnpm", "yarn", "go", "cargo", "dotnet",
    "ruff", "mypy", "tsc", "make", "git",
    # agent CLIs and shells used by the terminal profiles
    "hermes", "claude", "codex", "opencode", "gemini", "bash", "sh", "zsh", "pwsh", "powershell", "cmd",
})
_EXT = (".exe", ".cmd", ".bat", ".com", ".ps1")


class ExecDenied(PermissionError):
    pass


def exe_name(argv0: str) -> str:
    """Canonical executable name: basename, lowercase, no Windows extension, no version suffix on python."""
    base = os.path.basename(str(argv0).replace("\\", "/")).lower()
    for ext in _EXT:
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    if base.startswith("python") and base[6:].replace(".", "").isdigit():
        base = "python3" if base[6:].startswith("3") else "python"
    return base


def _mode(explicit: str | None, default: str) -> str:
    m = (explicit or os.environ.get("ANAMNESIA_EXEC_GUARD") or default).strip().lower()
    return m if m in MODES else default


def _audit(record: dict) -> None:
    try:
        from app.services.metrics import jsonl
        jsonl("exec_audit", record)
    except Exception:  # noqa: BLE001 -- auditing must never take the caller down
        pass


def _inside(path: str, roots: Sequence[str]) -> bool:
    p = os.path.normcase(os.path.realpath(path))
    for r in roots:
        rr = os.path.normcase(os.path.realpath(r))
        if p == rr or p.startswith(rr.rstrip(os.sep) + os.sep):
            return True
    return False


@dataclass
class ExecGuard:
    purpose: str
    default_mode: str = "enforce"
    mode: str | None = None
    allowlist: frozenset = field(default_factory=lambda: DEFAULT_ALLOWLIST)
    roots: Sequence[str] | None = None   # None = cwd not confined

    def effective_allowlist(self) -> set[str]:
        extra = {x.strip().lower() for x in os.environ.get("ANAMNESIA_EXEC_ALLOWLIST", "").split(",") if x.strip()}
        # the interpreter running the Gateway is always trusted (verifiers run tests with it)
        return set(self.allowlist) | extra | {exe_name(sys.executable)}

    def check(self, argv: Sequence[str] | None, cwd: str | None = None, *, timeout_s: float | None = None) -> str:
        """Audit + decide. Returns the decision ('allowed'|'warn'|'off'); raises ExecDenied when enforced."""
        mode = _mode(self.mode, self.default_mode)
        reasons: list[str] = []
        if not argv or not str(argv[0]).strip():
            reasons.append("empty_command")
            name = ""
        else:
            name = exe_name(argv[0])
            if name not in self.effective_allowlist():
                reasons.append("executable_not_allowlisted")
        if cwd is not None and self.roots is not None and not _inside(cwd, self.roots):
            reasons.append("cwd_outside_roots")
        decision = "allowed" if not reasons else {"enforce": "denied", "warn": "warn", "off": "off"}[mode]
        _audit({"event": "exec", "purpose": self.purpose, "decision": decision, "mode": mode,
                "exe": name, "argc": len(argv or []), "cwd": str(cwd) if cwd else None,
                "reasons": reasons, "timeout_s": timeout_s})
        if decision == "denied":
            raise ExecDenied(f"{self.purpose}: {','.join(reasons)} ({name or '?'})")
        return decision


def clamp_timeout(timeout_s: float | None, default: float = 60.0) -> float:
    try:
        t = float(timeout_s) if timeout_s is not None else default
    except (TypeError, ValueError):
        t = default
    return max(0.1, min(t, MAX_TIMEOUT_S))


def posix_limits(cpu_s: int = 120, mem_bytes: int = 4 * 1024 ** 3):
    """preexec_fn applying rlimits on POSIX; None on Windows (Job Objects are used by the PTY layer)."""
    if os.name != "posix":
        return None

    def _apply():  # pragma: no cover - POSIX only
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s))
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256)) if hasattr(resource, "RLIMIT_NPROC") else None
    return _apply
