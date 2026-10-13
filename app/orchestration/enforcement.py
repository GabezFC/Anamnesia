"""ANA-169 / ANA-173: how strongly a role's limits are ENFORCED, per launcher. Honest labels, no new blocking by default.

Levels (never claim more than the code does):
  hard         the executor has no tool surface at all (InProcessModelLauncher: text in, text out)
  soft         the role is told its limits in the prompt and `check_action` exists, but the PTY agent could ignore them
  best_effort  test doubles / unknown launchers

ANA-173 (opt-in, ANAMNESIA_ENFORCE_ROLES=1): `readonly_argv` builds a headless command line with the agent's own
read-only switches for read-only roles. Only switches VERIFIED against the installed CLI are marked `verified`;
anything else is returned with verified=False and must not be reported as `hard`.
`enforce` wraps `roles.check_action`: on denial it appends a `policy_denied` line to the chained policy audit.
"""
from __future__ import annotations

import os

from app.orchestration.roles import PermissionDenied, check_action, contract

LEVELS = ("hard", "soft", "best_effort")
# verified = confirmed in `<cli> --help` on this machine (claude); codex is not installed here.
_READ_ONLY_FLAGS = {
    "claude": {"argv": ["--permission-mode", "plan"], "verified": True,
               "note": "`claude --help` lists --permission-mode and --tools"},
    "codex": {"argv": ["-s", "read-only"], "verified": False,
              "note": "codex not installed here: flag from documentation, NOT verified"},
}


def enforce_roles_enabled() -> bool:
    return os.environ.get("ANAMNESIA_ENFORCE_ROLES", "").strip().lower() in ("1", "true", "on", "yes")


def enforcement_level(launcher, role: str) -> str:
    """Label for one step (ANA-169). Pure; informative only."""
    name = type(launcher).__name__
    if name == "InProcessModelLauncher":
        return "hard"
    if name == "TerminalLauncher":
        return "soft"
    return "best_effort"


def readonly_argv(agent: str, role: str) -> dict:
    """{'argv': [...], 'verified': bool, 'level': ...}. Writers get no extra flags."""
    c = contract(role)
    spec = _READ_ONLY_FLAGS.get(agent)
    if spec is None:
        return {"argv": [], "verified": False, "level": "best_effort", "note": "unknown agent"}
    if not c.read_only:
        return {"argv": [], "verified": spec["verified"], "level": "soft", "note": "role may write"}
    return {"argv": list(spec["argv"]), "verified": spec["verified"],
            "level": "hard" if spec["verified"] else "best_effort", "note": spec["note"]}


def enforce(role: str, action: str, target=None, cwd=None, *, run_id=None, step=None) -> None:
    """check_action + audit. Raises PermissionDenied when denied; callers gate the call on the flag."""
    try:
        check_action(role, action, target, cwd)
    except PermissionDenied as e:
        from app.policy.engine import audit
        audit("policy_denied", {"actor": role, "action": action, "target": str(target)[:200] if target else "",
                                "rule": "role_contract", "mode": "enforce", "run_id": run_id, "step": step,
                                "reason": str(e)[:200]})
        raise
