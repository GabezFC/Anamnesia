"""Adaptador Colibri (``coli``) - ANAM-034. Referencia verificada em ``Example Colibri/colibri/c/{coli,setup_flow}.py``.

Comandos usados (todos verificados no argparse do ``coli``): ``status --json``, ``plan --json --model --ram --ctx``,
``doctor --json --model``, ``serve --host --port --api-key --model``, ``stop --port``.
Porta propria (default 11500): nunca 8000 (default do Colibri) nem 11434 (Ollama). Host sempre 127.0.0.1.
A api key e gerada com ``secrets`` e fica so em memoria (nao e persistida nem aparece em status()).
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from typing import Optional

import app.services.local_ai.base as base
from app.services.local_ai.base import LocalRuntime, RuntimeError_, RuntimeStatus

HOME_ENV = "MG_COLIBRI_HOME"
DEFAULT_PORT = 11500
FORBIDDEN_PORTS = frozenset({8000, 11434})
TIMEOUT_S = 30.0


def default_setup_home() -> str:
    explicit = os.environ.get("COLI_SETUP_HOME")
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    if sys.platform == "win32":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local"), "colibri")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/colibri")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "colibri")


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


class ColibriRuntime(LocalRuntime):
    name = "colibri"

    def __init__(self, home: Optional[str] = None, port: int = DEFAULT_PORT, runner=None, http=None, spawner=None,
                 python: Optional[str] = None, timeout_s: float = TIMEOUT_S, key_via: str = "env",
                 key_factory=None, port_free=None):
        self.port = self.validate_port(port)
        self.host = base.LOOPBACK
        self._home = home or os.environ.get(HOME_ENV) or None
        self._run = runner or base.subprocess_runner
        self._http = http or base.http_json
        self._spawn = spawner or base.spawn_process
        self._python = python or sys.executable
        self._timeout = timeout_s
        self._key_via = key_via if key_via in ("arg", "env") else "env"
        self._key_factory = key_factory or (lambda: secrets.token_urlsafe(32))
        self._port_free = port_free or base.port_is_free
        self._key: Optional[str] = None
        self._proc = None

    # ---- validation
    @staticmethod
    def validate_port(port) -> int:
        try:
            p = int(port)
        except (TypeError, ValueError):
            raise RuntimeError_("bad_port", f"porta invalida: {port!r}") from None
        if p in FORBIDDEN_PORTS or not (base.USER_PORT_FLOOR <= p <= 65535):
            raise RuntimeError_("bad_port", f"porta {p} proibida/fora de 1024-65535 (8000=Colibri default, 11434=Ollama)")
        return p

    # ---- discovery
    def _config(self) -> tuple[dict, dict]:
        """(setup.json, install-state.json) de ``MG_COLIBRI_HOME``/home explicito, senao do setup home do Colibri."""
        for d in [self._home, default_setup_home()]:
            if not d:
                continue
            setup = _read_json(os.path.join(d, "setup.json"))
            if setup is not None:
                return setup, _read_json(os.path.join(d, "install-state.json")) or {}
        return {}, {}

    def _launcher(self) -> Optional[str]:
        setup, _ = self._config()
        cands = [setup.get("launcher")]
        if self._home:
            cands += [os.path.join(self._home, "c", "coli"), os.path.join(self._home, "coli")]
        for c in cands:
            if c and os.path.isfile(c):
                return c
        return None

    def _coli(self, *args) -> base.CmdResult:
        launcher = self._launcher()
        if not launcher:
            return base.CmdResult(None, error="launcher do coli nao encontrado")
        # herda o env (CUDA/Vulkan paths) e aponta o coli para o setup.json descoberto; nunca repassa a api key.
        env = dict(os.environ)
        sp = self._setup_path()
        if sp:
            env["COLI_SETUP_HOME"] = os.path.dirname(sp)
        env.pop("COLI_API_KEY", None)
        return self._run([self._python, launcher, *map(str, args)], self._timeout, env)

    def _setup_path(self) -> Optional[str]:
        for d in [self._home, default_setup_home()]:
            if d and os.path.isfile(os.path.join(d, "setup.json")):
                return os.path.join(d, "setup.json")
        return None

    def _json_cmd(self, *args) -> dict:
        r = self._coli(*args)
        if r.error or r.timed_out:
            return {"ok": False, "error": r.error or "timeout", "timed_out": r.timed_out}
        data = base.parse_json_tolerant(r.stdout)
        if data is None:
            return {"ok": False, "error": "saida nao-JSON do coli", "returncode": r.returncode,
                    "stderr": (r.stderr or "")[:200]}
        return {"ok": True, "data": data, "returncode": r.returncode}

    # ---- interface
    def detect(self) -> dict:
        setup, state = self._config()
        launcher = self._launcher()
        return {"runtime": self.name, "installed": bool(launcher), "launcher": launcher,
                "configured": bool(setup), "ready": setup.get("status") == "ready",
                "model_dir": setup.get("model_dir"), "model_name": (setup.get("model") or {}).get("name"),
                "backend": setup.get("backend"), "install_phase": state.get("phase"),
                "default_port_in_setup": setup.get("port")}

    def status(self) -> RuntimeStatus:
        d = self.detect()
        if not d["installed"]:
            return RuntimeStatus(self.name, False, "not_installed", reasons=["launcher do coli nao encontrado"])
        h = self.health()
        r = self._json_cmd("status", "--json")
        details = {k: d[k] for k in ("model_dir", "backend", "install_phase", "configured", "ready")}
        reasons = []
        if r["ok"] and isinstance(r["data"], dict):
            details["coli_status"] = {k: r["data"].get(k) for k in ("configured", "setup", "install")}
        else:
            reasons.append(f"coli status --json: {r.get('error')}")
        return RuntimeStatus(self.name, True, h["state"], self.base_url() if h["ok"] or self._proc else None,
                             d.get("model_name"), details, reasons)

    def plan(self, model: Optional[str], ram_gb: float, ctx: int) -> dict:
        model = model or self.detect().get("model_dir")
        if not model:
            return {"ok": False, "source": "coli plan", "error": "sem diretorio de modelo"}
        r = self._json_cmd("plan", "--json", "--model", model, "--ram", int(max(0, ram_gb)), "--ctx", int(ctx))
        if not r["ok"]:
            return {"ok": False, "source": "coli plan", "error": r["error"]}
        return {"ok": True, "source": "coli plan", "plan": r["data"]}

    def doctor(self, model: Optional[str] = None) -> dict:
        model = model or self.detect().get("model_dir")
        if not model:
            return {"ok": False, "error": "sem diretorio de modelo"}
        r = self._json_cmd("doctor", "--json", "--model", model)
        if not r["ok"]:
            return r
        data = r["data"]
        status = data.get("status") if isinstance(data, dict) else None
        return {"ok": status != "error", "report_status": status, "report": data}

    def health(self) -> dict:
        code, body = self._http("GET", f"http://{self.host}:{self.port}/health", {}, None, 3.0)
        if code == 200 and isinstance(body, dict) and body.get("status") == "ok":
            return {"ok": True, "state": "ready", "port": self.port}
        if self._proc is not None and getattr(self._proc, "poll", lambda: None)() is None:
            return {"ok": False, "state": "loading", "port": self.port}
        return {"ok": False, "state": "stopped", "port": self.port}

    def base_url(self) -> Optional[str]:
        return f"http://{self.host}:{self.port}/v1"

    def api_key(self) -> Optional[str]:
        return self._key

    def start(self, model: Optional[str] = None, **opts) -> RuntimeStatus:
        """Sobe ``coli serve`` como filho na porta propria. So em memoria: a key nunca e gravada."""
        from app.services.local_ai.policy import ensure_model_allowed
        d = self.detect()
        if not d["installed"]:
            raise RuntimeError_("not_installed", "Colibri nao encontrado (defina MG_COLIBRI_HOME)")
        model_dir = model or d.get("model_dir")
        if not model_dir:
            raise RuntimeError_("no_model", "sem diretorio de modelo")
        if opts.get("enforce_policy", True):
            model_id = (self._config()[0].get("model") or {}).get("id") or os.path.basename(str(model_dir).rstrip("/\\"))
            ensure_model_allowed(model_id, opts.get("mode"), opts.get("catalog_path"), opts.get("aliases"))
        if self._proc is not None and self._proc.poll() is None:
            return self.status()
        if not self._port_free(self.host, self.port):
            raise RuntimeError_("port_busy", f"porta {self.port} ocupada")
        self._key = self._key_factory()
        cmd = [self._python, self._launcher(), "serve", "--model", str(model_dir), "--host", self.host,
               "--port", str(self.port)]
        env = dict(os.environ)
        env.update({str(k): str(v) for k, v in (self._config()[0].get("env") or {}).items()})
        env.pop("COLI_API_KEY", None)
        if self._key_via == "env":
            env["COLI_API_KEY"] = self._key
        else:
            cmd += ["--api-key", self._key]
        self._proc = self._spawn(cmd, env, None)
        return RuntimeStatus(self.name, True, "loading", self.base_url(), d.get("model_name"),
                             {"port": self.port, "pid": getattr(self._proc, "pid", None)})

    def stop(self) -> dict:
        r = self._coli("stop", "--port", self.port)
        out = {"ok": bool(r.returncode == 0), "returncode": r.returncode, "error": r.error}
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                out["terminated_child"] = True
            except OSError as exc:
                out["error"] = f"{type(exc).__name__}"
        self._key = None
        return out
