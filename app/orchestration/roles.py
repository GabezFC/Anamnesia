"""Role contracts (spec §2). Pure data + checks; nothing here executes anything.

researcher / reviewer are READ-ONLY (reviewer may also run tests); implementer writes only inside the project cwd.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ACTIONS = ("read_memory", "read_files", "write_files", "run_tests", "run_commands")


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class RoleContract:
    name: str
    allowed_actions: frozenset
    write_scope: str          # "none" | "project_cwd"
    input_desc: str
    output_format: str
    max_output_lines: int
    task_kind: str            # router task kind used to pick the model

    @property
    def read_only(self) -> bool:
        return "write_files" not in self.allowed_actions


CONTRACTS = {
    "orchestrator": RoleContract(
        "orchestrator", frozenset({"read_memory"}), "none",
        "task + memory summary", "plan and decisions, short", 40, "general"),
    "researcher": RoleContract(
        "researcher", frozenset({"read_memory", "read_files"}), "none",
        "one objective question", "findings, each with its source (file or note); no prose padding", 30, "general"),
    "implementer": RoleContract(
        "implementer", frozenset({"read_memory", "read_files", "write_files", "run_tests"}), "project_cwd",
        "small task + files", "diff + 3-line summary", 60, "code"),
    "reviewer": RoleContract(
        "reviewer", frozenset({"read_memory", "read_files", "run_tests"}), "none",
        "diff + tests", "first line APPROVED or CHANGES_REQUESTED, then a list of problems", 30, "general"),
}


def contract(role: str) -> RoleContract:
    try:
        return CONTRACTS[role]
    except KeyError:
        raise PermissionDenied(f"unknown role {role!r}") from None


def _inside(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def check_action(role: str, action: str, target=None, cwd=None) -> None:
    """Raise PermissionDenied unless `role` may do `action`. Writes need `target` inside `cwd` (symlinks resolved)."""
    c = contract(role)
    if action not in ACTIONS:
        raise PermissionDenied(f"unknown action {action!r}")
    if action not in c.allowed_actions:
        raise PermissionDenied(f"role {role} may not {action}")
    if action == "write_files":
        if target is None or cwd is None:
            raise PermissionDenied("write_files needs a target and the project cwd")
        base = Path(os.path.realpath(cwd))
        p = Path(target)
        p = p if p.is_absolute() else base / p
        if not _inside(Path(os.path.realpath(p)), base):
            raise PermissionDenied(f"write outside the project cwd: {target}")


def role_prompt(role: str, task: str, prior: str = "", result_hint: str = "") -> str:
    c = contract(role)
    allowed = ", ".join(sorted(c.allowed_actions))
    rules = [f"You are the {role} sub-agent. Allowed actions: {allowed}."]
    if c.read_only:
        rules.append("READ-ONLY: do not modify any file.")
    if c.write_scope == "project_cwd":
        rules.append("Write only inside the project working directory.")
    rules.append(f"Output format: {c.output_format}. At most {c.max_output_lines} lines.")
    parts = ["\n".join(rules), "## Task\n" + task.strip()]
    if prior.strip():
        parts.append("## Previous steps\n" + prior.strip())
    if result_hint:
        parts.append(result_hint)
    return "\n\n".join(parts) + "\n"
