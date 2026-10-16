"""LocalProvider: fala OpenAI-compativel (``/chat/completions``) com qualquer ``LocalRuntime``.

Reusa ``GenerationResult``/``failure`` do ``app.adapters.models.providers``. Nao usa ``ensure_paid_allowed`` (local,
custo de API = 0) mas mantem ``ensure_online`` e exige loopback. Tokens: usa ``usage`` do servidor quando existe;
``count_tokens`` e SEMPRE estimado.
"""
from __future__ import annotations

import json
import time
from typing import Iterator, Optional

import httpx

from app.adapters.models.providers import GenerationResult, failure
from app.services.local_ai.base import LocalRuntime, RuntimeError_
from app.services.local_ai.policy import ensure_model_allowed
from app.services.offline import ensure_online, is_loopback_url
from app.services.token_estimate import estimate_tokens


class NotSupported(RuntimeError):
    pass


class LocalProvider:
    def __init__(self, runtime: LocalRuntime, model: str, timeout_s: float = 600, client: Optional[httpx.Client] = None,
                 mode: Optional[str] = None, enforce_policy: bool = True, catalog_path: Optional[str] = None,
                 aliases: Optional[dict] = None, extra_body: Optional[dict] = None):
        self.runtime = runtime
        self.provider = runtime.name
        self.model = model
        self.timeout_s = timeout_s
        self._client = client
        self.extra_body = dict(extra_body or {})
        self.policy = ensure_model_allowed(model, mode, catalog_path, aliases) if enforce_policy else None

    # -- helpers
    def _base(self) -> str:
        url = self.runtime.base_url()
        if not url:
            raise RuntimeError_("no_server", f"{self.provider}: sem servidor")
        if not is_loopback_url(url):
            raise RuntimeError_("not_loopback", "LocalProvider so fala com loopback")
        ensure_online(self.provider, url)
        return url.rstrip("/")

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        key = self.runtime.api_key()
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def _body(self, prompt, temperature, max_tokens, stream=False) -> dict:
        msgs = prompt if isinstance(prompt, list) else [{"role": "user", "content": prompt}]
        body = {"model": self.model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens,
                **self.extra_body}
        if stream:
            body["stream"] = True
        return body

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=self.timeout_s)

    # -- API
    def generate(self, prompt, temperature: float = 0.0, max_tokens: int = 800) -> GenerationResult:
        t0 = time.perf_counter()
        try:
            base = self._base()
            r = self._http().post(f"{base}/chat/completions", json=self._body(prompt, temperature, max_tokens),
                                  headers=self._headers())
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            answer = data["choices"][0]["message"].get("content")
            return GenerationResult(answer, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                                    round((time.perf_counter() - t0) * 1000, 1), self.provider, self.model)
        except Exception as exc:  # noqa: BLE001
            return failure(exc, t0, self.provider, self.model)

    def stream(self, prompt, temperature: float = 0.0, max_tokens: int = 800) -> Iterator[str]:
        """Gera deltas de texto (SSE ``data: {...}`` / ``data: [DONE]``). Erros sobem como excecao."""
        base = self._base()
        with self._http().stream("POST", f"{base}/chat/completions", json=self._body(prompt, temperature, max_tokens, True),
                                 headers=self._headers()) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    chunk = json.loads(payload)
                    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                except (ValueError, AttributeError, IndexError):
                    continue
                if delta.get("content"):
                    yield delta["content"]

    def count_tokens(self, text: str) -> dict:
        return {"tokens": estimate_tokens(text or ""), "estimated": True}

    def estimate_cost(self, input_tokens: int = 0, output_tokens: int = 0) -> dict:
        return {"api_cost_usd": 0.0, "local": True, "note": "custo de API zero; energia/hardware nao contabilizados"}
