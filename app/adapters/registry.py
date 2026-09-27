"""Consumer registry: resolves (agent, provider, model) -> something with .generate(prompt), and detects
what is REALLY available (§76, §103, §112). Nothing is shown as available unless it can run."""
from __future__ import annotations

import os
import shutil
import threading
import time
from functools import lru_cache

from config.agents import AgentsConfig
from app.adapters.agents.agents import ClaudeCodeAdapter, CodexAdapter, HermesAdapter, OpenCodeAdapter
from app.adapters.models.providers import (AnthropicAdapter, OllamaAdapter, OpenAICompatibleAdapter,
                                           OpenAIAdapter, OpenRouterAdapter, VLLMAdapter)

AGENTS = ("hermes", "claude_code", "codex", "opencode", "generic")


def detect_models(cfg: AgentsConfig | None = None) -> dict:
    cfg = cfg or AgentsConfig()
    ok, models = OllamaAdapter(cfg.ollama_base_url).available()
    out = {
        "ollama": {"available": ok, "models": models, "base_url": cfg.ollama_base_url},
        "anthropic": {"available": bool(os.getenv("ANTHROPIC_API_KEY")), "models": [],
                      "reason": None if os.getenv("ANTHROPIC_API_KEY") else "ANTHROPIC_API_KEY ausente"},
        "openai": {"available": bool(os.getenv("OPENAI_API_KEY")), "models": [],
                   "reason": None if os.getenv("OPENAI_API_KEY") else "OPENAI_API_KEY ausente"},
        "openrouter": {"available": bool(os.getenv("OPENROUTER_API_KEY")), "models": [],
                       "reason": None if os.getenv("OPENROUTER_API_KEY") else "OPENROUTER_API_KEY ausente"},
        "vllm": {"available": False, "models": [], "reason": "vLLM não instalado/servidor não detectado"},
    }
    try:
        vm = VLLMAdapter(cfg.vllm_base_url, "").list_models()
        out["vllm"] = {"available": True, "models": vm, "reason": None}
    except Exception:  # noqa: BLE001
        pass
    return out


@lru_cache(maxsize=1)
def _detect_agents_cached() -> tuple:
    cfg = AgentsConfig()
    return tuple(a.available() for a in (HermesAdapter(cfg), ClaudeCodeAdapter(cfg), CodexAdapter(cfg),
                                         OpenCodeAdapter(cfg)))


# detect_models() probes Ollama and vLLM over the network, costing 8.6-10.6 s. Measured
# 2026-09-27: with no cache at all GET /system/info took 34 s, and with a plain TTL cache every
# expiry made one unlucky request pay the full probe again (8.8 s observed). That endpoint is
# called on every dashboard page load, so a user returning after the TTL saw the UI hang.
#
# Strategy: stale-while-revalidate. A cached value is ALWAYS returned immediately; when it is
# older than _MODELS_TTL_S a single background thread refreshes it for the next caller. Only the
# very first call (empty cache) blocks. Availability changes rarely, so serving a slightly stale
# answer is far better than making a user wait. refresh=True forces a synchronous probe.
_MODELS_TTL_S = 60.0
_models_cache: dict[str, object] = {"at": 0.0, "value": None}
_models_lock = threading.Lock()
_models_refreshing = threading.Event()


def _refresh_models_now() -> dict:
    value = detect_models()
    with _models_lock:
        _models_cache["at"], _models_cache["value"] = time.monotonic(), value
    return value


def _refresh_models_bg() -> None:
    # Event guards against piling up threads when several requests arrive during a refresh.
    if _models_refreshing.is_set():
        return
    _models_refreshing.set()

    def work() -> None:
        try:
            _refresh_models_now()
        except Exception:  # noqa: BLE001 — a failed probe must never break the request path
            pass
        finally:
            _models_refreshing.clear()

    threading.Thread(target=work, name="detect-models-refresh", daemon=True).start()


def _detect_models_cached(refresh: bool = False) -> dict:
    if refresh:
        return _refresh_models_now()
    with _models_lock:
        cached = _models_cache["value"]
        age = time.monotonic() - float(_models_cache["at"])
    if cached is None:
        return _refresh_models_now()  # cold start: nothing to serve, must block once
    if age >= _MODELS_TTL_S:
        _refresh_models_bg()  # serve stale now, fresh next time
    return cached  # type: ignore[return-value]


def detect_all(refresh: bool = False) -> dict:
    if refresh:
        _detect_agents_cached.cache_clear()
    agents = list(_detect_agents_cached())
    models = _detect_models_cached(refresh)
    agents.append({"agent": "generic", "available": any(m["available"] for m in models.values()),
                   "version": None, "mcp": False, "cli": False, "metrics": "FULL",
                   "reason": "API direta (Ollama/OpenAI-compatible/Anthropic)"})
    return {"agents": agents, "models": models, "graphify": shutil.which("graphify") is not None}


def warm_detection() -> None:
    """Probe agents and models in the background at startup so no user request pays for it.

    Called from the FastAPI lifespan. Without this the first /system/info after boot blocks for
    ~9 s on the network probes, which is exactly when someone is opening the dashboard.
    """
    def work() -> None:
        try:
            _detect_agents_cached()
            _refresh_models_now()
        except Exception:  # noqa: BLE001 — warming is best-effort, never fatal
            pass

    threading.Thread(target=work, name="detect-warm", daemon=True).start()


class GenericConsumer:
    """Direct model call without an agent (provider in ollama|vllm|openai|openrouter|anthropic|openai_compatible)."""

    def __init__(self, provider: str, model: str, cfg: AgentsConfig | None = None):
        cfg = cfg or AgentsConfig()
        self.provider, self.model = provider, model
        if provider == "ollama":
            self.impl = OllamaAdapter(cfg.ollama_base_url, model)
        elif provider == "vllm":
            self.impl = VLLMAdapter(cfg.vllm_base_url, model)
        elif provider == "openai":
            self.impl = OpenAIAdapter(model)
        elif provider == "openrouter":
            self.impl = OpenRouterAdapter(model)
        elif provider == "anthropic":
            self.impl = AnthropicAdapter(model)
        elif provider == "openai_compatible":
            self.impl = OpenAICompatibleAdapter(cfg.openai_compat_base_url, model or cfg.openai_compat_model,
                                                os.getenv("OPENAI_COMPAT_API_KEY"))
        else:
            raise ValueError(f"provider desconhecido: {provider}")

    def generate(self, prompt: str):
        cfg = AgentsConfig()
        return self.impl.generate(prompt, temperature=cfg.generation_temperature, max_tokens=cfg.generation_max_tokens)


class AgentConsumer:
    def __init__(self, agent: str, provider: str | None, model: str | None):
        self.agent, self.provider, self.model = agent, provider, model
        self.impl = {"hermes": HermesAdapter, "claude_code": ClaudeCodeAdapter, "codex": CodexAdapter,
                     "opencode": OpenCodeAdapter}[agent]()

    def generate(self, prompt: str):
        if self.agent == "hermes":
            return self.impl.generate(prompt, model=self.model, provider=self.provider)
        return self.impl.generate(prompt, model=self.model)


def get_consumer(agent: str, provider: str | None = None, model: str | None = None):
    if agent == "generic":
        if not provider or not model:
            raise ValueError("generic exige provider e model")
        return GenericConsumer(provider, model)
    if agent not in AGENTS:
        raise ValueError(f"agente desconhecido: {agent}")
    return AgentConsumer(agent, provider, model)
