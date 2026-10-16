"""Adaptador Ollama - ANAM-034. API nativa verificada em docs/api.md do repo ollama/ollama (2026-10-15):
``GET /api/version``, ``GET /api/tags``, ``GET /api/ps``, ``POST /api/generate`` (``keep_alive``; prompt vazio carrega o
modelo e ``keep_alive: 0`` descarrega). OpenAI-compativel em ``/v1`` (ENVIRONMENT.md). Nada e baixado (sem /api/pull).
"""
from __future__ import annotations

import shutil
from typing import Optional

import app.services.local_ai.base as base
from app.services.local_ai.base import LocalRuntime, RuntimeError_, RuntimeStatus

DEFAULT_URL = "http://127.0.0.1:11434"
_KV_GB_PER_1K_CTX = 0.1   # heuristica GROSSEIRA, rotulada estimated no plano


class OllamaRuntime(LocalRuntime):
    name = "ollama"

    def __init__(self, url: str = DEFAULT_URL, http=None, runner=None, spawner=None, which=None, timeout_s: float = 5.0):
        from app.services.offline import is_loopback_url
        if not is_loopback_url(url):
            raise RuntimeError_("not_loopback", "Ollama gerenciado so em loopback")
        self.url = url.rstrip("/")
        self._http = http or base.http_json
        self._spawn = spawner or base.spawn_process
        self._which = which or shutil.which
        self._timeout = timeout_s
        self._proc = None

    def _get(self, path: str):
        return self._http("GET", f"{self.url}{path}", {}, None, self._timeout)

    def detect(self) -> dict:
        exe = self._which("ollama")
        code, body = self._get("/api/version")
        running = code == 200 and isinstance(body, dict)
        return {"runtime": self.name, "installed": bool(exe) or running, "binary": exe, "running": running,
                "version": body.get("version") if running else None}

    def _models(self) -> Optional[list]:
        code, body = self._get("/api/tags")
        if code == 200 and isinstance(body, dict) and isinstance(body.get("models"), list):
            return [m for m in body["models"] if isinstance(m, dict)]
        return None

    def status(self) -> RuntimeStatus:
        d = self.detect()
        if not d["installed"]:
            return RuntimeStatus(self.name, False, "not_installed", reasons=["ollama nao encontrado no PATH nem em execucao"])
        if not d["running"]:
            return RuntimeStatus(self.name, True, "stopped", None, details={"binary": d["binary"]})
        names = [m.get("name") for m in (self._models() or [])]
        code, ps = self._get("/api/ps")
        loaded = [m.get("name") for m in (ps or {}).get("models", [])] if code == 200 and isinstance(ps, dict) else []
        return RuntimeStatus(self.name, True, "ready", self.base_url(), loaded[0] if loaded else None,
                             {"version": d["version"], "models": names, "loaded": loaded})

    def plan(self, model: Optional[str], ram_gb: float, ctx: int) -> dict:
        """Estimativa (``estimated``): tamanho em disco do modelo (``size`` de /api/tags) + KV heuristico vs RAM informada."""
        models = self._models()
        if models is None:
            return {"ok": False, "source": "ollama /api/tags", "error": "ollama indisponivel"}
        hit = next((m for m in models if model in (m.get("name"), m.get("model"))), None)
        if hit is None:
            return {"ok": False, "source": "ollama /api/tags", "error": f"modelo {model!r} nao instalado (nao sera baixado)"}
        weights = float(hit.get("size") or 0) / 1e9
        kv = _KV_GB_PER_1K_CTX * max(0, ctx) / 1024.0
        need = weights + kv
        return {"ok": True, "source": "ollama /api/tags", "estimated": True,
                "estimate": {"weights_gb": round(weights, 2), "kv_gb": round(kv, 2), "total_gb": round(need, 2),
                             "ram_gb": ram_gb, "fits": bool(ram_gb and need <= ram_gb * 0.85),
                             "note": "heuristica; Ollama nao expoe plano de recursos"}}

    def start(self, model: Optional[str] = None, **opts) -> RuntimeStatus:
        """Garante servidor (``ollama serve`` como filho, se nao estiver rodando) e, se ``model`` dado, o carrega (sem pull)."""
        d = self.detect()
        if not d["installed"]:
            raise RuntimeError_("not_installed", "ollama nao encontrado")
        if not d["running"]:
            if not d["binary"]:
                raise RuntimeError_("not_running", "servidor Ollama parado e binario ausente")
            self._proc = self._spawn([d["binary"], "serve"], base.minimal_env(), None)
            return RuntimeStatus(self.name, True, "loading", self.base_url(), details={"spawned": True})
        if model:
            from app.services.local_ai.policy import ensure_model_allowed
            if opts.get("enforce_policy", True):
                ensure_model_allowed(model, opts.get("mode"), opts.get("catalog_path"), opts.get("aliases"))
            self._http("POST", f"{self.url}/api/generate", {}, {"model": model, "keep_alive": opts.get("keep_alive", "5m")},
                       opts.get("timeout_s", 120.0))
        return self.status()

    def stop(self, model: Optional[str] = None) -> dict:
        """Descarrega o(s) modelo(s) (``keep_alive: 0``); encerra o servidor so se foi criado por este objeto."""
        code, ps = self._get("/api/ps")
        targets = [model] if model else ([m.get("name") for m in ps.get("models", [])] if code == 200 and isinstance(ps, dict) else [])
        unloaded = []
        for t in filter(None, targets):
            c, _ = self._http("POST", f"{self.url}/api/generate", {}, {"model": t, "keep_alive": 0}, self._timeout)
            if c == 200:
                unloaded.append(t)
        out = {"ok": True, "unloaded": unloaded}
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            out["terminated_child"] = True
        return out

    def health(self) -> dict:
        code, body = self._get("/api/version")
        ok = code == 200 and isinstance(body, dict)
        return {"ok": ok, "state": "ready" if ok else "stopped", "version": body.get("version") if ok else None}

    def base_url(self) -> Optional[str]:
        return f"{self.url}/v1"
