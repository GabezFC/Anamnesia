"""Interface ``LocalRuntime`` + utilitarios compartilhados (subprocess/HTTP injetaveis, parser tolerante)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

LOOPBACK = "127.0.0.1"
USER_PORT_FLOOR = 1024

# Variaveis de ambiente repassadas a processos-filho (o resto, incl. segredos, NAO herda).
_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "HOME",
                    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "LANG", "LC_ALL")


class RuntimeError_(RuntimeError):
    """Falha de runtime com ``code`` estavel (``not_installed``, ``bad_port``, ``port_busy`` ...)."""

    def __init__(self, code: str, msg: str):
        super().__init__(f"{code}: {msg}")
        self.code = code
        self.msg = msg


@dataclass
class CmdResult:
    returncode: Optional[int]
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: Optional[str] = None


Runner = Callable[[list, float, Optional[dict]], CmdResult]
Http = Callable[[str, str, dict, Optional[dict], float], "tuple[Optional[int], Any]"]  # method,url,headers,json,timeout


def subprocess_runner(cmd: list, timeout: float, env: Optional[dict] = None) -> CmdResult:
    """Runner padrao: nunca levanta; timeout/erro viram campos do resultado."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return CmdResult(None, timed_out=True, error=f"timeout apos {timeout}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return CmdResult(None, error=f"{type(exc).__name__}: {exc}"[:300])
    return CmdResult(r.returncode, r.stdout or "", r.stderr or "")


def http_json(method: str, url: str, headers: dict, body: Optional[dict], timeout: float):
    """HTTP padrao (httpx). Devolve ``(status|None, json|None)``; nunca levanta."""
    import httpx
    try:
        r = httpx.request(method, url, headers=headers or None, json=body, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def spawn_process(cmd: list, env: dict, cwd: Optional[str] = None):
    """Spawner padrao: processo-filho sem janela, saida descartada (evita bloqueio de pipe)."""
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)


def minimal_env(extra: Optional[dict] = None) -> dict:
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    for k, v in (extra or {}).items():
        env[str(k)] = str(v)
    return env


def parse_json_tolerant(text: Any) -> Optional[Any]:
    """Extrai o primeiro objeto/array JSON de uma saida possivelmente suja (banner, ANSI, lixo). ``None`` se nao houver."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch in "{[":
            try:
                obj, _ = dec.raw_decode(s[i:])
            except ValueError:
                continue
            if isinstance(obj, (dict, list)):
                return obj
    return None


def port_is_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


@dataclass
class RuntimeStatus:
    runtime: str
    installed: bool
    state: str = "unknown"     # not_installed|stopped|loading|ready|error|unknown
    base_url: Optional[str] = None
    model: Optional[str] = None
    details: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class LocalRuntime(ABC):
    """Contrato comum dos runtimes locais. Segredos (api key) nunca saem em ``status()``/``to_dict()``."""
    name = "local"
    local = True

    @abstractmethod
    def detect(self) -> dict:
        """Somente leitura: o runtime existe/esta pronto? Nao executa nem inicia nada pesado."""

    @abstractmethod
    def status(self) -> RuntimeStatus: ...

    @abstractmethod
    def plan(self, model: Optional[str], ram_gb: float, ctx: int) -> dict:
        """``{ok, source, plan|estimate, error}``; numeros rotulados ``estimated`` quando nao medidos."""

    @abstractmethod
    def start(self, model: Optional[str] = None, **opts) -> RuntimeStatus: ...

    @abstractmethod
    def stop(self) -> dict: ...

    @abstractmethod
    def health(self) -> dict:
        """``{ok: bool, state: str, ...}``; nunca levanta."""

    @abstractmethod
    def base_url(self) -> Optional[str]:
        """Base OpenAI-compativel (``http://127.0.0.1:PORT/v1``) ou ``None`` se nao ha servidor conhecido."""

    def api_key(self) -> Optional[str]:
        return None
