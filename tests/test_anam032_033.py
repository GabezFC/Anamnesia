"""ANAM-032 (Ollama num_ctx/keep_alive/truncamento/health real) + ANAM-033 (privacidade fail-closed)."""
from __future__ import annotations

import http.server
import json
import threading

import pytest

from app.adapters.models import providers as pv
from app.routing import health as hl
from app.routing.escalation import next_model
from app.routing.policy import preset
from app.routing.registry import Registry
from app.routing.registry import load_registry
from app.routing.router import RoutingDecision, route


# ---------------------------------------------------------------- fake Ollama (native API)
class _H(http.server.BaseHTTPRequestHandler):
    reply: dict = {}
    chat_status = 200
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": "qwen3:8b"}, {"name": "llama3:8b"}]})
        if self.path == "/api/ps":
            return self._send(200, {"models": [{"name": "qwen3:8b"}]})
        self._send(404, {"error": "nope"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _H.seen.append((self.path, body))
        if self.path != "/api/chat":
            return self._send(404, {"error": "nope"})
        if _H.chat_status != 200:
            return self._send(_H.chat_status, {"error": "model does not support think"})
        self._send(200, {"message": {"role": "assistant", "content": "pong"}, "done": True, "done_reason": "stop",
                         "prompt_eval_count": 10, "eval_count": 2, **_H.reply})


@pytest.fixture
def ollama():
    _H.reply, _H.chat_status, _H.seen = {}, 200, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("ANAMNESIA_OLLAMA_NUM_CTX", "ANAMNESIA_OLLAMA_KEEP_ALIVE", "ANAMNESIA_HEALTH_PROBE"):
        monkeypatch.delenv(k, raising=False)
    hl._PROBE_CACHE.clear()


# ---------------------------------------------------------------- ANAM-032
def test_ollama_uses_native_chat_and_sends_nothing_unconfigured(ollama):
    r = pv.OllamaAdapter(ollama, "qwen3:8b").generate("ping", max_tokens=5)
    assert (r.answer, r.input_tokens, r.output_tokens, r.error) == ("pong", 10, 2, None)
    path, body = _H.seen[-1]
    assert path == "/api/chat" and body["stream"] is False
    assert "num_ctx" not in body["options"] and "keep_alive" not in body       # never sent unless configured
    assert body["options"]["num_predict"] == 5 and body["think"] is False


def test_ollama_sends_num_ctx_and_keep_alive_when_configured(ollama):
    pv.OllamaAdapter(ollama, "qwen3:8b", num_ctx=16384, keep_alive="10m").generate("ping")
    body = _H.seen[-1][1]
    assert body["options"]["num_ctx"] == 16384 and body["keep_alive"] == "10m"


def test_ollama_env_config_and_validation(ollama, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_OLLAMA_NUM_CTX", "8192")
    monkeypatch.setenv("ANAMNESIA_OLLAMA_KEEP_ALIVE", "-1")
    a = pv.OllamaAdapter(ollama)
    assert a.num_ctx == 8192 and a.keep_alive == -1
    with pytest.raises(ValueError):
        pv.OllamaAdapter(ollama, num_ctx=0)


def test_ollama_think_rejected_is_retried_without_think(ollama):
    class A(pv.OllamaAdapter):
        n = 0

        def _post(self, body):
            A.n += 1
            if "think" in body:
                import httpx
                req = httpx.Request("POST", "http://x/api/chat")
                resp = httpx.Response(400, text='{"error":"does not support think"}', request=req)
                raise httpx.HTTPStatusError("400", request=req, response=resp)
            return super()._post(body)
    r = A(ollama, "m").generate("ping")
    assert r.answer == "pong" and A.n == 2 and "think" not in _H.seen[-1][1]


def test_truncation_flags(ollama):
    ok = pv.OllamaAdapter(ollama, num_ctx=4096).generate("curto")
    assert ok.truncated is False
    _H.reply = {"done_reason": "length"}
    assert pv.OllamaAdapter(ollama).generate("x").truncated is True
    _H.reply = {"prompt_eval_count": 4096}
    cut = pv.OllamaAdapter(ollama, num_ctx=4096).generate("x")
    assert cut.truncated is True and "prompt_filled_num_ctx" in cut.raw_meta["truncated_reasons"]
    _H.reply = {"prompt_eval_count": 100}                      # prompt far larger than what the server evaluated
    big = pv.OllamaAdapter(ollama).generate("palavra " * 2000)
    assert big.truncated is True and "prompt_below_estimate" in big.raw_meta["truncated_reasons"]


def test_probe_ollama_real_distinguishes_installed_and_running(ollama, monkeypatch):
    assert "skipped" in hl.probe_ollama(ollama)
    monkeypatch.setenv("ANAMNESIA_HEALTH_PROBE", "1")
    p = hl.probe_ollama(ollama, model="llama3:8b")
    assert p["ok"] and p["runtime_running"] and p["models"] == 2
    assert p["loaded_models"] == ["qwen3:8b"]
    assert p["model_installed"] is True and p["model_loaded"] is False
    assert hl.probe_ollama(ollama, model="qwen3:8b")["model_loaded"] is True


def test_probe_ollama_down_is_not_running(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HEALTH_PROBE", "1")
    p = hl.probe_ollama("http://127.0.0.1:9")            # discard port: nothing listens
    assert p["ok"] is False and p["runtime_running"] is False


def test_probe_ollama_cache_10s(ollama, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HEALTH_PROBE", "1")
    a = hl.probe_ollama(ollama)
    assert a["ok"]
    assert (ollama, None) in hl._PROBE_CACHE and hl.probe_ollama(ollama)["latency_ms"] == a["latency_ms"]


# ---------------------------------------------------------------- ANAM-033
def test_loopback_classification():
    for u in ("http://localhost:11434", "http://127.0.0.1:8001/v1", "http://[::1]:8000", "http://127.5.5.5/v1"):
        assert pv.endpoint_is_loopback(u), u
    for u in ("https://api.openai.com/v1", "http://192.168.0.5:8000", "http://0.0.0.0:8000", "", None, "nonsense",
              "http://localhost.evil.com"):
        assert not pv.endpoint_is_loopback(u), u


def test_private_to_remote_adapter_fails_closed_without_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no request may be built")
    monkeypatch.setattr(pv.httpx, "post", boom)
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    for ad in (pv.OpenAIAdapter("gpt"), pv.OpenRouterAdapter("m"),
               pv.OpenAICompatibleAdapter("https://colibri.example.com/v1", "m", None, "openai_compatible"),
               pv.OllamaAdapter("http://10.0.0.7:11434")):
        r = ad.generate("segredo", private=True)
        assert r.answer is None and r.error_kind == pv.PRIVACY_BLOCKED and "PrivacyBlocked" in r.error


def test_private_anthropic_blocked_before_sdk(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    r = pv.AnthropicAdapter("claude").generate("segredo", private=True)
    assert r.error_kind == pv.PRIVACY_BLOCKED


def test_private_to_loopback_is_allowed(ollama):
    r = pv.OllamaAdapter(ollama).generate("segredo", private=True)
    assert r.error is None and r.answer == "pong"
    r2 = pv.OpenAICompatibleAdapter("http://127.0.0.1:9/v1", "m", None, "openai_compatible", timeout_s=1) \
        .generate("x", private=True)
    assert r2.error_kind != pv.PRIVACY_BLOCKED          # got past the gate (then fails on connection)


def test_public_data_unchanged_by_privacy_param(ollama):
    assert pv.OllamaAdapter(ollama).generate("x", private=False).answer == "pong"


def _registry():
    return load_registry()


def _policy():
    return preset("balanced", True)


def test_router_private_picks_only_local_and_filters_chain():
    reg = _registry()
    d = route("explique algo", 0, "memory", "medium", reg, _policy(), private=True)
    assert d.private is True
    assert d.model_id is not None and reg.get(d.model_id).local
    assert all(reg.get(m).local for m in d.fallback_chain)
    assert set(d.allowed_models) == {m.id for m in reg.models if m.local and not m.planned and m.id in d.allowed_models}
    pub = route("explique algo", 0, "memory", "medium", reg, _policy())
    assert pub.private is False and pub.allowed_models is None


def test_router_private_no_local_model_fails_closed():
    reg = _registry()
    remote = Registry(models=[m for m in reg.models if not m.local], file_hash=reg.file_hash, version=reg.version)
    assert remote.models
    d = route("x", 0, "memory", "medium", remote, _policy(), private=True)
    assert d.model_id is None and d.fallback_chain == [] and "privacy_blocked_no_local_model" in d.reason_codes
    assert d.allowed_models == []
    # the same registry still routes (to cloud) when the data is public: proves the block is the privacy gate
    assert route("x", 0, "memory", "medium", remote, _policy()).model_id is not None


def test_escalation_respects_allowed_models():
    d = RoutingDecision("a", 1, None, "NONE", 0.1, [], "", "", ["cloud-1", "local-2", "cloud-3"], "unavailable", 0, 3, {})
    assert next_model(d, 1) == "cloud-1"                              # legacy behaviour untouched
    assert next_model(d, 1, allowed={"local-2"}) == "local-2"
    assert next_model(d, 2, allowed={"local-2"}) is None
    d.allowed_models = ["local-2"]                                    # private decision
    assert next_model(d, 1) == "local-2" and next_model(d, 2) is None
    d.allowed_models = []
    assert next_model(d, 1) is None                                   # fail closed, never an unfiltered entry


def test_choose_next_never_leaves_private_allowed_set():
    from app.routing import resilience as rs
    reg = _registry()
    d = route("explique algo", 0, "memory", "medium", reg, _policy(), private=True)
    assert d.model_id
    cur = reg.get(d.model_id)
    for act in (rs.Action(rs.SWITCH_PROVIDER, 0.0, "t"), rs.Action(rs.ESCALATE_TIER, 0.0, "t"),
                rs.Action(rs.SKIP_PROVIDER, 0.0, "t")):
        nxt = rs.choose_next(d, reg, cur, "timeout", act, {cur.id}, 1, set())
        assert nxt is None or nxt in d.allowed_models
