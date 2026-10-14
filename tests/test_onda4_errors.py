"""ANA-171 (taxonomia de erro de provider) + ANA-168 (kill-switch global de gasto). Offline: servidor HTTP local fake."""
from __future__ import annotations

import http.server
import threading
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.adapters.models import errors as E
from app.adapters.models.providers import AnthropicAdapter, GenerationResult, OpenAICompatibleAdapter


# ---------------------------------------------------------------- pure mapping
@pytest.mark.parametrize("status,body,kind", [
    (401, "", "auth"), (403, "", "auth"), (429, "", "rate_limit"), (408, "", "timeout"), (504, "", "timeout"),
    (404, "model 'x' not found", "model_not_found"), (404, "", "model_not_found"), (404, "no route", "other"),
    (400, "This model's maximum context length is 8192 tokens", "context_overflow"),
    (413, "", "context_overflow"), (400, "model does not exist", "model_not_found"), (400, "openai/x is not a valid model ID", "model_not_found"), (400, "bad json", "other"),
    (500, "", "provider_down"), (502, "", "provider_down"), (503, "", "provider_down"), (200, "", "other"),
])
def test_status_mapping(status, body, kind):
    assert E.kind_from_status(status, body) == kind
    assert kind in E.ERROR_KINDS


def test_every_kind_is_reachable_and_valid():
    reached = {E.kind_from_status(s, b) for s, b in [(401, ""), (429, ""), (504, ""), (400, "context length"),
                                                     (404, "model"), (500, ""), (400, "x")]}
    reached |= {E.classify_exception(ValueError("x"))[0], E.classify_exception(httpx.ConnectError("x"))[0],
                E.classify_exception(httpx.ReadTimeout("x"))[0]}
    assert reached == set(E.ERROR_KINDS)


def test_retry_after_parsing():
    assert E.parse_retry_after("7") == 7.0
    assert E.parse_retry_after("0") == 0.0
    assert E.parse_retry_after("-3") == 0.0
    assert E.parse_retry_after(None) is None and E.parse_retry_after("") is None and E.parse_retry_after("abc") is None
    assert E.parse_retry_after("nan") is None and E.parse_retry_after("inf") is None
    now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)
    date = (now + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert E.parse_retry_after(date, now=now) == 30.0
    past = (now - timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert E.parse_retry_after(past, now=now) == 0.0


# ---------------------------------------------------------------- real HTTP against a local fake
class _Handler(http.server.BaseHTTPRequestHandler):
    plan: dict = {}

    def log_message(self, format, *args):  # noqa: A002 - silence
        pass

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        self.rfile.read(n)
        status, body, headers = self.plan.get(self.path, (200, b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":3,"completion_tokens":1}}', {}))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _gen(base, status, body=b"{}", headers=None, provider="ollama"):
    _Handler.plan = {"/chat/completions": (status, body, headers or {})}
    return OpenAICompatibleAdapter(base, "m", None, provider, timeout_s=3).generate("hi")


def test_success_has_no_error_kind(server):
    r = _gen(server, 200, b'{"choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":3,"completion_tokens":1}}')
    assert r.error is None and r.error_kind is None and r.answer == "ok"


@pytest.mark.parametrize("status,body,kind", [
    (401, b'{"error":"bad key"}', "auth"), (429, b'{"error":"slow"}', "rate_limit"),
    (500, b'{"error":"boom"}', "provider_down"), (400, b'{"error":"maximum context length exceeded"}', "context_overflow"),
    (404, b'{"error":"model not found"}', "model_not_found"),
])
def test_http_failures_are_classified(server, status, body, kind):
    r = _gen(server, status, body)
    assert r.answer is None and r.error and r.error_kind == kind and r.status_code == status


def test_retry_after_header_is_captured(server):
    r = _gen(server, 429, b"{}", {"Retry-After": "12"})
    assert r.error_kind == "rate_limit" and r.retry_after == 12.0


def test_bad_output_shape(server):
    r = _gen(server, 200, b'{"unexpected": true}')
    assert r.error_kind == "bad_output" and r.answer is None


def test_connection_refused_is_provider_down():
    import socket
    with socket.socket() as sk:                 # a port that was free a moment ago -> connection refused
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    r = OpenAICompatibleAdapter(f"http://127.0.0.1:{port}", "m", None, "ollama", timeout_s=2).generate("hi")
    assert r.error_kind == "provider_down" and r.status_code is None


def test_timeout_is_classified():
    class Slow(_Handler):
        def do_POST(self):
            import time
            time.sleep(1.5)
            super().do_POST()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = OpenAICompatibleAdapter(f"http://127.0.0.1:{srv.server_address[1]}", "m", None, "ollama", timeout_s=0.3).generate("hi")
        assert r.error_kind == "timeout"
    finally:
        srv.shutdown()


def test_error_never_contains_the_api_key(server):
    _Handler.plan = {"/chat/completions": (401, b'{"error":"bad"}', {})}
    r = OpenAICompatibleAdapter(server, "m", "sk-SECRET-VALUE-123456", "openai", timeout_s=3).generate("hi")
    assert "sk-SECRET-VALUE-123456" not in (r.error or "") and r.error_kind == "auth"


def test_generation_result_to_dict_has_new_fields():
    d = GenerationResult("a", 1, 1, 1.0, "p", "m").to_dict()
    assert d["error_kind"] is None and d["status_code"] is None and d["retry_after"] is None


# ---------------------------------------------------------------- ANA-168 kill-switch
@pytest.mark.parametrize("val", ["0", "false", "no", "off", "OFF", " False "])
def test_paid_calls_off_values(monkeypatch, val):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", val)
    assert E.paid_calls_enabled() is False


@pytest.mark.parametrize("val", [None, "", "1", "true", "yes"])
def test_paid_calls_default_and_on(monkeypatch, val):
    if val is None:
        monkeypatch.delenv("ANAMNESIA_PAID_CALLS", raising=False)
    else:
        monkeypatch.setenv("ANAMNESIA_PAID_CALLS", val)
    assert E.paid_calls_enabled() is True
    E.ensure_paid_allowed("openai")      # no raise


def test_kill_switch_blocks_every_cloud_provider_and_spares_local(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "0")
    for p in ("openai", "anthropic", "openrouter", "huggingface", "nvidia", "claude_code", "codex", None):
        with pytest.raises(E.PaidCallsDisabled):
            E.ensure_paid_allowed(p)
    for p in ("ollama", "vllm", "OLLAMA"):
        E.ensure_paid_allowed(p)


def test_adapters_do_not_touch_the_network_when_off(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "0")

    def boom(*a, **k):
        raise AssertionError("network call attempted with the kill-switch on")
    monkeypatch.setattr(httpx, "post", boom)
    r = OpenAICompatibleAdapter("https://api.openai.com/v1", "m", "k", "openai").generate("x")
    assert r.answer is None and "ANAMNESIA_PAID_CALLS=0" in r.error and r.error_kind == "other"
    r2 = AnthropicAdapter("claude-x").generate("x")
    assert r2.answer is None and "ANAMNESIA_PAID_CALLS=0" in r2.error


def test_make_adapter_zero_cloud_adapters_with_flag_off(monkeypatch):
    from app.routing import answer as ans
    from app.routing.registry import load_registry
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "0")
    built = []
    for m in load_registry().models:
        try:
            built.append((m, ans.make_adapter(m, {})))
        except E.PaidCallsDisabled:
            assert not E.is_local_provider(m.provider)
        except ValueError:
            pass            # provider without adapter (huggingface/nvidia): nothing to build either
    assert built and all(E.is_local_provider(m.provider) for m, _ in built)


def test_answer_mode_records_error_kind_when_paid_calls_off(monkeypatch):
    from app.routing import answer as ans
    from app.routing.policy import preset
    from app.routing.registry import ModelEntry, Registry
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "0")
    cloud = ModelEntry("c1", "openai", "gpt-x", 2, None, (), False, None, False, True)
    reg = Registry(models=[cloud], file_hash="h", version=1)
    monkeypatch.setattr(ans, "get_registry", lambda: reg)
    monkeypatch.setattr(ans, "get_policy", lambda: preset("balanced", enabled=True))
    monkeypatch.setattr(ans, "get_availability", lambda: {"openai": {"available": True}})

    class Cand:
        decision, snippet, source_file, section = "KEEP", "O backend usa Python e FastAPI.", "a.md", "S"

    class Res:
        query = "qual o backend?"
        metrics = {"context_tokens": 10, "pipeline": "baseline"}
        candidates = [Cand()]
        run_id = None

    extras = ans._answer(None, Res(), "low", "memory", {"mode_requested": "answer", "mode_used": "context",
                                                        "routing": None, "grounding": None, "attempts": []})
    att = extras["attempts"][0]
    assert extras["mode_used"] == "context" and att["error"] and att["error_kind"] == "other"
