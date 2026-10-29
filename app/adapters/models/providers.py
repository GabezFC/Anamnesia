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
from urllib.parse import urlsplit

import httpx

from app.adapters.models.errors import classify_exception, ensure_paid_allowed
from app.services.egress import check_egress
from app.services.offline import ensure_online, is_loopback_host


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
    # ANA-171: machine-readable failure cause (None on success); see app/adapters/models/errors.py
    error_kind: str | None = None
    status_code: int | None = None
    retry_after: float | None = None
    # ANAM-032: True when the prompt was cut by the context window or the answer by max_tokens (None = unknown)
    truncated: bool | None = None

    def to_dict(self):
        return dict(self.__dict__)


class PrivacyBlocked(PermissionError):
    """ANAM-033: private data was about to be sent to a non-loopback endpoint. Fail-closed, never silent."""


PRIVACY_BLOCKED = "privacy_blocked"   # error_kind of a GenerationResult refused by the privacy gate


def endpoint_is_loopback(base_url: str | None) -> bool:
    """True only for an explicit loopback URL (localhost, 127.0.0.0/8, ::1). Empty/invalid/wildcard -> False."""
    try:
        host = urlsplit((base_url or "").strip()).hostname
    except ValueError:
        return False
    return bool(host) and host not in ("0.0.0.0", "::") and is_loopback_host(host)


def ensure_private_safe(provider: str, base_url: str | None) -> None:
    """ANAM-033: private data may only go to a loopback endpoint (local Ollama/vLLM/Colibri/openai-compat).
    Anything else -- every hosted provider included -- raises `PrivacyBlocked` BEFORE a request is built."""
    if not endpoint_is_loopback(base_url):
        raise PrivacyBlocked(f"dado privado nao pode ser enviado ao provider '{provider}' "
                             f"(destino nao-loopback); falha fechada (ANAM-033)")


def failure(exc: BaseException, t0: float, provider: str, model: str) -> GenerationResult:
    """GenerationResult for a raised exception, with the ANA-171 taxonomy filled in."""
    kind, status, retry = classify_exception(exc)
    if isinstance(exc, PrivacyBlocked):
        kind = PRIVACY_BLOCKED
    return GenerationResult(None, None, None, round((time.perf_counter() - t0) * 1000, 1), provider, model,
                            f"{type(exc).__name__}: {str(exc)[:300]}", error_kind=kind, status_code=status,
                            retry_after=retry)


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
        check_egress(self.base_url, self.provider)  # ANAM-005
        r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=5)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 800,
                 private: bool = False) -> GenerationResult:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature, "max_tokens": max_tokens, **self.extra_body}
        t0 = time.perf_counter()
        try:
            if private:
                ensure_private_safe(self.provider, self.base_url)   # ANAM-033: first, before anything else
            ensure_paid_allowed(self.provider)          # ANA-168 kill-switch (local providers exempt)
            ensure_online(self.provider, self.base_url)  # ANA-224: OFFLINE=1 allows loopback only
            check_egress(self.base_url, self.provider)   # ANAM-005: allow-list de hosts
            r = httpx.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers(),
                           timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            usage = data.get("usage") or {}
            answer = data["choices"][0]["message"].get("content")
            return GenerationResult(answer, usage.get("prompt_tokens"), usage.get("completion_tokens"),
                                    round((time.perf_counter() - t0) * 1000, 1), self.provider, self.model)
        except Exception as exc:  # noqa: BLE001
            return failure(exc, t0, self.provider, self.model)


def _parse_keep_alive(value):
    """Ollama `keep_alive`: duration string ("10m") or number of seconds (-1 = forever, 0 = unload)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("keep_alive invalido")
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value).strip())
    except ValueError:
        return str(value).strip()


class OllamaAdapter(OpenAICompatibleAdapter):
    """Ollama via the NATIVE `POST /api/chat` (ANAM-032). Why not `/v1`: Ollama's OpenAI-compatibility doc says the
    OpenAI API has no way to set the context size; `options.num_ctx` and `keep_alive` exist only on the native
    endpoints (docs/api.md, docs/faq.mdx; see Cérebro IA (Anamnesia/Guias-de-usuario-2026-10-24/ENVIRONMENT.md)). `num_ctx`/`keep_alive` are sent ONLY
    when configured (ctor or ANAMNESIA_OLLAMA_NUM_CTX / ANAMNESIA_OLLAMA_KEEP_ALIVE); otherwise the server
    defaults apply (4096 tokens / 5m) and truncation can only be detected, not prevented."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3:8b", timeout_s: float = 600,
                 num_ctx: int | None = None, keep_alive=None, think: bool | None = False):
        super().__init__(base_url.rstrip("/") + "/v1", model, None, "ollama", timeout_s)
        self.native_url = base_url.rstrip("/")
        if num_ctx is None:
            raw = os.getenv("ANAMNESIA_OLLAMA_NUM_CTX", "").strip()
            num_ctx = int(raw) if raw else None
        if num_ctx is not None and int(num_ctx) <= 0:
            raise ValueError("num_ctx deve ser > 0")
        self.num_ctx = None if num_ctx is None else int(num_ctx)
        self.keep_alive = _parse_keep_alive(keep_alive if keep_alive is not None
                                            else os.getenv("ANAMNESIA_OLLAMA_KEEP_ALIVE"))
        self.think = think    # False replaces the old /v1 `reasoning_effort: none`; None = do not send

    def available(self) -> tuple[bool, list[str]]:
        try:
            check_egress(self.native_url, "ollama")  # ANAM-005
            r = httpx.get(f"{self.native_url}/api/tags", timeout=3)
            r.raise_for_status()
            return True, [m["name"] for m in r.json().get("models", [])]
        except Exception:  # noqa: BLE001
            return False, []

    def loaded_models(self) -> list[str]:
        """Models currently in memory (`GET /api/ps`); [] when the runtime is down."""
        try:
            check_egress(self.native_url, "ollama")
            r = httpx.get(f"{self.native_url}/api/ps", timeout=3)
            r.raise_for_status()
            return [m.get("name") for m in r.json().get("models", [])]
        except Exception:  # noqa: BLE001
            return []

    def build_body(self, prompt: str, temperature: float, max_tokens: int, with_think: bool = True) -> dict:
        options: dict = {"temperature": temperature, "num_predict": max_tokens}
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        body: dict = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                      "stream": False, "options": options}
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        if with_think and self.think is not None:
            body["think"] = self.think
        return body

    def _post(self, body: dict):
        r = httpx.post(f"{self.native_url}/api/chat", json=body, timeout=self.timeout_s)
        r.raise_for_status()
        return r

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 800,
                 private: bool = False) -> GenerationResult:
        t0 = time.perf_counter()
        try:
            if private:
                ensure_private_safe(self.provider, self.native_url)   # ANAM-033
            ensure_paid_allowed(self.provider)
            ensure_online(self.provider, self.native_url)
            check_egress(self.native_url, self.provider)
            try:
                r = self._post(self.build_body(prompt, temperature, max_tokens))
            except httpx.HTTPStatusError as exc:
                # models without thinking support may reject `think` with 400: retry once without it.
                if (self.think is None or exc.response.status_code != 400
                        or "think" not in (exc.response.text or "").lower()):
                    raise
                r = self._post(self.build_body(prompt, temperature, max_tokens, with_think=False))
            data = r.json()
            if data.get("error"):
                raise RuntimeError(str(data["error"])[:300])
            answer = (data.get("message") or {}).get("content")
            p_tok, o_tok = data.get("prompt_eval_count"), data.get("eval_count")
            truncated, meta = self._truncation(prompt, data, p_tok)
            return GenerationResult(answer, p_tok, o_tok, round((time.perf_counter() - t0) * 1000, 1),
                                    self.provider, self.model, truncated=truncated, raw_meta=meta)
        except Exception as exc:  # noqa: BLE001
            return failure(exc, t0, self.provider, self.model)

    def _truncation(self, prompt: str, data: dict, prompt_tokens: int | None):
        """(truncated, meta). Answer cut: done_reason == "length". Prompt cut: reported prompt tokens fill
        num_ctx, or are far below the (heuristic) estimate. meta lists the reasons so a false positive is
        auditable; truncated is None when nothing can be said."""
        meta: dict = {"done_reason": data.get("done_reason"), "num_ctx_sent": self.num_ctx,
                      "load_duration_ns": data.get("load_duration")}
        reasons = []
        if data.get("done_reason") == "length":
            reasons.append("output_max_tokens")
        if prompt_tokens is not None:
            from app.services.token_estimate import estimate_tokens
            est = estimate_tokens(prompt)
            meta["estimated_prompt_tokens"] = est
            if self.num_ctx is not None and prompt_tokens >= self.num_ctx:
                reasons.append("prompt_filled_num_ctx")
            elif est >= 64 and prompt_tokens < 0.8 * est:
                reasons.append("prompt_below_estimate")
        elif not reasons:
            return None, meta
        meta["truncated_reasons"] = reasons
        return bool(reasons), meta


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

    def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 800,
                 private: bool = False) -> GenerationResult:
        t0 = time.perf_counter()
        try:
            base = os.getenv("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
            if private:
                ensure_private_safe("anthropic", base)   # ANAM-033: remote unless explicitly loopback
            ensure_paid_allowed("anthropic")             # ANA-168 kill-switch
            check_egress(base, "anthropic")  # ANAM-005
            import anthropic
            client = anthropic.Anthropic(timeout=self.timeout_s)
            msg = client.messages.create(model=self.model, max_tokens=max_tokens, temperature=temperature,
                                         messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in msg.content)
            return GenerationResult(text, msg.usage.input_tokens, msg.usage.output_tokens,
                                    round((time.perf_counter() - t0) * 1000, 1), "anthropic", self.model)
        except Exception as exc:  # noqa: BLE001
            return failure(exc, t0, "anthropic", self.model)
