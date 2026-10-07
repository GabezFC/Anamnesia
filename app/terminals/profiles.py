"""Launch profiles (config/profiles.yaml): which command a session runs and which extra env keys it gets."""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.routing.registry import RegistryError, _parse_yaml

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "profiles.yaml"


class ProfileError(ValueError):
    pass


class ProfileUnavailable(ProfileError):
    """The profile's command was not found on PATH."""


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    command: str
    kind: str = "agent"
    args: tuple[str, ...] = ()
    env_keys: tuple[str, ...] = ()
    windows_command: str | None = None
    windows_args: tuple[str, ...] | None = None
    description: str = ""

    def candidates(self) -> list[str]:
        if sys.platform == "win32":
            return [self.windows_command or self.command]
        cands = [self.command]
        if self.kind == "shell" and self.id == "shell":
            cands = [os.environ.get("SHELL") or "", "bash", "sh"]
        return [c for c in cands if c]

    def resolve(self) -> str | None:
        for c in self.candidates():
            found = shutil.which(c)
            if found:
                return found
        return None

    def argv(self) -> list[str]:
        exe = self.resolve()
        if not exe:
            raise ProfileUnavailable(f"comando não encontrado: {self.candidates()[0]}")
        args = self.windows_args if (sys.platform == "win32" and self.windows_args is not None) else self.args
        return [exe, *args]

    def missing_env_keys(self, environ=None) -> list[str]:
        env = os.environ if environ is None else environ
        return [k for k in self.env_keys if not env.get(k)]

    def describe(self) -> dict:
        """Public view: never includes env values, only whether declared keys are missing."""
        return {"id": self.id, "name": self.name, "kind": self.kind, "description": self.description,
                "command": (self.windows_command or self.command) if sys.platform == "win32" else self.command,
                "available": self.resolve() is not None, "env_keys": list(self.env_keys),
                "missing_env_keys": self.missing_env_keys()}


def _str_list(v, where) -> tuple[str, ...]:
    if v is None:
        return ()
    if not isinstance(v, list):
        raise ProfileError(f"{where}: deve ser lista")
    return tuple(str(x) for x in v)


def load_profiles(path=None) -> dict[str, Profile]:
    p = Path(path) if path else DEFAULT_PATH
    try:
        doc = _parse_yaml(p.read_text(encoding="utf-8"))
    except (OSError, RegistryError) as e:
        raise ProfileError(f"não foi possível ler {p}: {e}") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("profiles"), list):
        raise ProfileError("profiles.yaml precisa de uma lista 'profiles'")
    out: dict[str, Profile] = {}
    for i, raw in enumerate(doc["profiles"]):
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("command"):
            raise ProfileError(f"profiles[{i}]: 'id' e 'command' são obrigatórios")
        pid = str(raw["id"])
        if pid in out:
            raise ProfileError(f"id duplicado: {pid}")
        out[pid] = Profile(
            id=pid, name=str(raw.get("name") or pid), command=str(raw["command"]),
            kind=str(raw.get("kind") or "agent"), args=_str_list(raw.get("args"), f"{pid}.args"),
            env_keys=_str_list(raw.get("env_keys"), f"{pid}.env_keys"),
            windows_command=str(raw["windows_command"]) if raw.get("windows_command") else None,
            windows_args=(_str_list(raw["windows_args"], f"{pid}.windows_args")
                          if "windows_args" in raw else None),
            description=str(raw.get("description") or ""))
    return out
