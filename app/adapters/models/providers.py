"""Model provider adapters (§32, §36, §37). One generic OpenAI-compatible client covers Ollama, vLLM,
OpenRouter and other gateways; Anthropic has its own adapter. Every adapter returns the same shape:

    {"answer": str|None, "input_tokens": int|None, "output_tokens": int|None, "latency_ms": float,
     "provider": str, "model": str, "error": str|None}
Tokens the provider does not report are None (never estimated).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import httpx


@dataclass
class GenerationResult:
    answer: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float
    provider: str
    model: str
    error: str | None = None
    agent_tokens: int | None = None
    agent_cost: float | None = None
    raw_meta: dict | None = None

    def to_dict(self):
        return dict(self.__dict__)


class OpenAICompatibleAdapter:
    """Chat Completions over HTTP (`POST {base_url}/chat/completions`). Verified with Ollama 0.34 `/v1`."""

    def __init__(self, base_url: str, model: str, api_key: str | None = None, provider: str = "openai_compatible",
                 timeout_s: float = 600, extra_body: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.provider = provider
        self.timeout_s = timeout_s
        self.extra_body = extra_body or {}

    def _headers(self):
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def list_models(self) -> list[str]:
        r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=5)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 800) -> GenerationResult:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens, **self.extra_body}
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers(),
                           timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            answer = data["choices"][0]["message"].get("content")
            return GenerationResult(answer, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                                    round((time.perf_counter() - t0) * 1000, 1), self.provider, self.model)
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(None, None, None, round((time.perf_counter() - t0) * 1000, 1),
                                    self.provider, self.model, f"{type(exc).__name__}: {str(exc)[:300]}")


class OllamaAdapter(OpenAICompatibleAdapter):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3:8b", timeout_s: float = 600):
        # Ollama's OpenAI-compatible endpoint lives under /v1.
        # `reasoning_effort: none` disables qwen3 thinking so the answer is not spent on hidden reasoning.
        super().__init__(base_url.rstrip("/") + "/v1", model, None, "ollama", timeout_s,
                         extra_body={"reasoning_effort": "none"})
        self.native_url = base_url.rstrip("/")

    def available(self) -> tuple[bool, list[str]]:
        try:
            r = httpx.get(f"{self.native_url}/api/tags", timeout=3)
            r.raise_for_status()
            return True, [m["name"] for m in r.json().get("models", [])]
        except Exception:  # noqa: BLE001
            return False, []


class VLLMAdapter(OpenAICompatibleAdapter):
    """vLLM serves the OpenAI API; not installed in this environment -> prepared, untested."""

    def __init__(self, base_url: str, model: str, timeout_s: float = 600):
        super().__init__(base_url, model, os.getenv("VLLM_API_KEY"), "vllm", timeout_s)


class OpenRouterAdapter(OpenAICompatibleAdapter):
    def __init__(self, model: str, timeout_s: float = 600):
        super().__init__("https://openrouter.ai/api/v1", model, os.getenv("OPENROUTER_API_KEY"), "openrouter", timeout_s)


class OpenAIAdapter(OpenAICompatibleAdapter):
    def __init__(self, model: str, timeout_s: float = 600):
        super().__init__("https://api.openai.com/v1", model, os.getenv("OPENAI_API_KEY"), "openai", timeout_s)


class AnthropicAdapter:
    """Anthropic Messages API via the official `anthropic` SDK. Requires ANTHROPIC_API_KEY."""
    provider = "anthropic"

    def __init__(self, model: str, timeout_s: float = 600):
        self.model = model
        self.timeout_s = timeout_s

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 800) -> GenerationResult:
        t0 = time.perf_counter()
        try:
            import anthropic
            client = anthropic.Anthropic(timeout=self.timeout_s)
            msg = client.messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature,
                                         messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            return GenerationResult(text, msg.usage.input_tokens, msg.usage.output_tokens,
                                    round((time.perf_counter() - t0) * 1000, 1), "anthropic", self.model)
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(None, None, None, round((time.perf_counter() - t0) * 1000, 1),
                                    "anthropic", self.model, f"{type(exc).__name__}: {str(exc)[:300]}")
