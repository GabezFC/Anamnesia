"""Gerente do processo-filho do Laya (modo `worker`).

Por que existe: o Gateway roda num Python sem `torch`/`laya`; o pacote vive num venv próprio (data/local_ai/venv*),
e o `laya-serve` desse venv não tem fastapi/uvicorn (extra `serve` não instalado) — logo `inproc` e `serve` ficavam
OFF e a integração "falhava" em silêncio. O worker reaproveita o venv que já existe, sem instalar nada.

Garantias: sem rede (HF_HUB_OFFLINE), sem herdar segredos do ambiente, timeout de carga e de chamada, no máximo UMA
reinicialização por chamada (nunca laço), stderr em arquivo de log (sem conteúdo do usuário: o worker só imprime erros
estruturados no stdout).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

WORKER_SCRIPT = Path(__file__).with_name("laya_worker.py")
_ENV_PASS = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME", "USERPROFILE",
             "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "LANG", "LC_ALL")


class WorkerError(RuntimeError):
    """Falha do worker (não iniciou, expirou, morreu, resposta inválida). `kind` é estável para métricas."""

    def __init__(self, kind: str, msg: str):
        super().__init__(f"{kind}: {msg}")
        self.kind = kind


def venv_python(venv: Path) -> Optional[Path]:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = venv / rel
        if p.is_file():
            return p
    return None


def venv_has_laya(py: Path) -> bool:
    """Checagem barata (sem executar): o venv tem o pacote `laya` em site-packages?"""
    root = py.parent.parent
    for sp in (root / "Lib" / "site-packages", *sorted((root / "lib").glob("python*/site-packages"))):
        if (sp / "laya" / "__init__.py").is_file():
            return True
    return False


def discover_python(explicit: str = "", roots: Optional[list] = None) -> tuple[Optional[str], str]:
    """(caminho, origem). Ordem: MG_LAYA_PYTHON explícito -> data/local_ai/venv* com `laya` instalado."""
    if explicit.strip():
        p = Path(explicit.strip()).expanduser()
        return (str(p), "MG_LAYA_PYTHON") if p.is_file() else (None, f"MG_LAYA_PYTHON inexistente: {p}")
    if roots is None:
        from config.paths import PACKAGE_ROOT, data_dir
        roots = [Path(data_dir()) / "local_ai", Path(PACKAGE_ROOT) / "data" / "local_ai"]
    seen = set()
    for r in roots:
        r = Path(r)
        if str(r) in seen or not r.is_dir():
            continue
        seen.add(str(r))
        for v in sorted(r.glob("venv*")):
            py = venv_python(v)
            if py and venv_has_laya(py):
                return str(py), f"autodetectado em {v}"
    return None, "nenhum venv com 'laya' em data/local_ai/venv*"


def worker_env() -> dict:
    env = {k: os.environ[k] for k in _ENV_PASS if k in os.environ}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false"})
    return env


class LayaWorker:
    def __init__(self, python: str, multilingual: str, english: str = "", device: str = "", threads: int = 0,
                 load_timeout_s: float = 120.0, log_path: Optional[Path] = None, popen=None):
        self.python, self.multilingual, self.english = python, multilingual, english
        self.device, self.threads, self.load_timeout_s = device, threads, load_timeout_s
        self.log_path = log_path
        self._popen = popen or subprocess.Popen
        self._proc = None
        self._q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._lock = threading.Lock()
        self._seq = 0
        self.load_ms: Optional[float] = None
        self.laya_version = ""
        self.starts = 0

    # ---- ciclo de vida
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _pump(self, proc) -> None:
        try:
            for line in proc.stdout:
                self._q.put(line)
        finally:
            self._q.put(None)

    def _start(self) -> None:
        cmd = [self.python, str(WORKER_SCRIPT), "--multilingual", self.multilingual]
        if self.english:
            cmd += ["--english", self.english]
        if self.device:
            cmd += ["--device", self.device]
        if self.threads > 0:
            cmd += ["--threads", str(self.threads)]
        err = subprocess.DEVNULL
        if self.log_path is not None:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                err = open(self.log_path, "ab")  # noqa: SIM115 (fechado com o processo)
            except OSError:
                err = subprocess.DEVNULL
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            self._proc = self._popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                     env=worker_env(), text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, creationflags=flags)
        except OSError as exc:
            raise WorkerError("spawn", f"{type(exc).__name__}: {exc}"[:200]) from exc
        self.starts += 1
        self._q = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc,), daemon=True).start()
        t0 = time.monotonic()
        try:
            line = self._q.get(timeout=self.load_timeout_s)
        except queue.Empty:
            self.stop()
            raise WorkerError("load_timeout", f"pesos não carregaram em {self.load_timeout_s:.0f}s") from None
        if line is None:
            rc = self._proc.poll()
            self.stop()
            raise WorkerError("died_on_start", f"processo terminou (rc={rc}); veja {self.log_path}")
        try:
            msg = json.loads(line)
        except ValueError:
            self.stop()
            raise WorkerError("bad_handshake", "saída não-JSON no handshake") from None
        if not msg.get("ready"):
            self.stop()
            raise WorkerError("load_failed", str(msg.get("error") or "falha ao carregar")[:200])
        self.load_ms = msg.get("load_ms") or round((time.monotonic() - t0) * 1000, 1)
        self.laya_version = str(msg.get("laya") or "")

    def stop(self) -> None:
        p, self._proc = self._proc, None
        if p is None:
            return
        try:
            if p.stdin:
                p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except OSError:
                pass

    # ---- chamada
    def _call_once(self, requests: list, batch_size: Optional[int], timeout_s: float) -> list:
        if not self.alive():
            self._start()
        self._seq += 1
        mid = self._seq
        try:
            self._proc.stdin.write(json.dumps({"id": mid, "requests": requests, "batch_size": batch_size},
                                              ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self.stop()
            raise WorkerError("pipe", f"{type(exc).__name__}") from exc
        deadline = time.monotonic() + timeout_s
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                self.stop()   # resposta tardia contaminaria a próxima chamada: derruba e recomeça limpo
                raise WorkerError("call_timeout", f"sem resposta em {timeout_s:.0f}s")
            try:
                line = self._q.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                self.stop()
                raise WorkerError("died", "worker terminou durante a chamada")
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise WorkerError("inference", str(msg["error"])[:200])
            return msg["results"]

    def predict_batch(self, requests: list, batch_size: Optional[int] = None, timeout_s: float = 20.0) -> list:
        """No máximo 2 tentativas (1 + 1 reinício) e só se o processo MORREU/travou; erro de inferência não repete."""
        with self._lock:
            try:
                return self._call_once(requests, batch_size, timeout_s)
            except WorkerError as exc:
                if exc.kind not in ("died", "pipe", "call_timeout", "died_on_start"):
                    raise
            return self._call_once(requests, batch_size, timeout_s)   # única reinicialização
