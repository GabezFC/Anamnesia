"""Onda 4 / ANA-214 (partial) + ANA-171/177/178: OpenAICompatibleAdapter against a LOCAL fake HTTP server.

No real network, no key: a http.server on 127.0.0.1 answers per *model name* with 401/429+Retry-After/
timeout/400-overflow/404/500/garbage/418, so every ERROR_KIND is exercised end to end, and the retry
driver runs on the real adapter with fake sleep/clock.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.adapters.models.errors import ERROR_KINDS
from app.adapters.models.providers import OpenAICompatibleAdapter
from app.routing import retry as rt

OK_BODY = {"choices": [{"message": {"content": "ola"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}


class _Fake(BaseHTTPRequestHandler):
    counts: dict = {}

    def log_message(self, *a):  # silence
        pass

    def _send(self, code, body, headers=None):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        model = json.loads(self.rfile.read(n) or b"{}").get("model", "")
        c = self.counts[model] = self.counts.get(model, 0) + 1
        if model == "auth":
            self._send(401, {"error": {"message": "bad key"}})
        elif model == "rl":
            self._send(429, {"error": {"message": "slow down"}}, {"Retry-After": "2"})
        elif model == "rl_once":
            self._send(429, {"error": {"message": "slow"}}, {"Retry-After": "3"}) if c == 1 else self._send(200, OK_BODY)
        elif model == "slow":
            time.sleep(0.8)
            try:
                self._send(200, OK_BODY)
            except OSError:
                pass
        elif model == "overflow":
            self._send(400, {"error": {"message": "This model's maximum context length is 8192 tokens"}})
        elif model == "nomodel":
            self._send(404, {"error": {"message": "The model `nomodel` does not exist"}})
        elif model == "boom":
            self._send(500, {"error": {"message": "internal"}})
        elif model == "boom_twice":
            self._send(503, {"error": {"message": "unavailable"}}) if c <= 2 else self._send(200, OK_BODY)
        elif model == "garbage":
            self._send(200, {"unexpected": True})
        elif model == "teapot":
            self._send(418, {"error": {"message": "teapot"}})
        else:
            self._send(200, OK_BODY)


@pytest.fixture(scope="module")
def base_url():
    _Fake.counts = {}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1"
    srv.shutdown()
    srv.server_close()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "1")   # ANAM-003: explicit consent (default is now OFF)


def gen(base_url, model, timeout_s=5.0):
    return OpenAICompatibleAdapter(base_url, model, "k", "fakecloud", timeout_s).generate("hi")


def test_ok_has_no_error_kind(base_url):
    r = gen(base_url, "fine")
    assert r.answer == "ola" and r.error is None and r.error_kind is None


@pytest.mark.parametrize("model,kind,status", [
    ("auth", "auth", 401), ("rl", "rate_limit", 429), ("overflow", "context_overflow", 400),
    ("nomodel", "model_not_found", 404), ("boom", "provider_down", 500), ("garbage", "bad_output", None),
    ("teapot", "other", 418)])
def test_taxonomy_over_http(base_url, model, kind, status):
    r = gen(base_url, model)
    assert r.answer is None and r.error_kind == kind and r.status_code == status


def test_rate_limit_carries_retry_after(base_url):
    assert gen(base_url, "rl").retry_after == 2.0


def test_timeout_kind(base_url):
    r = gen(base_url, "slow", timeout_s=0.2)
    assert r.error_kind == "timeout" and r.status_code is None


def test_provider_down_when_port_closed():
    r = OpenAICompatibleAdapter("http://127.0.0.1:9/v1", "x", "k", "fakecloud", 1.0).generate("hi")
    assert r.error_kind == "provider_down"


def test_paid_kill_switch_is_other_and_local_is_exempt(base_url, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_PAID_CALLS", "0")
    assert gen(base_url, "fine").error_kind == "other"
    r = OpenAICompatibleAdapter(base_url, "fine", None, "ollama", 5).generate("hi")
    assert r.answer == "ola"


def test_every_error_kind_is_covered_by_this_file():
    covered = {"auth", "rate_limit", "context_overflow", "model_not_found", "provider_down", "bad_output",
               "other", "timeout"}
    assert covered == set(ERROR_KINDS)


# -- retry driver on the real adapter, fake time -----------------------------------------------------
class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s

    def now(self):
        return self.t


def test_retry_honours_retry_after_then_succeeds(base_url):
    c = Clock()
    out = rt.call_with_retry(lambda: gen(base_url, "rl_once"), rt.RetryPolicy(), sleep=c.sleep, clock=c.now)
    assert out.result.answer == "ola" and out.retries == 1 and c.sleeps == [3.0] and out.gave_up is None


def test_retry_5xx_backoff_then_success(base_url):
    c = Clock()
    out = rt.call_with_retry(lambda: gen(base_url, "boom_twice"), rt.RetryPolicy(jitter=0.0),
                             sleep=c.sleep, clock=c.now)
    assert out.result.answer == "ola" and out.retries == 2 and c.sleeps == [0.5, 1.0]


def test_retry_gives_up_on_persistent_429_and_never_retries_auth(base_url):
    c = Clock()
    out = rt.call_with_retry(lambda: gen(base_url, "rl"), rt.RetryPolicy(), sleep=c.sleep, clock=c.now)
    assert out.gave_up == "max_retries" and out.result.error_kind == "rate_limit" and c.sleeps == [2.0, 2.0]
    c2, before = Clock(), _Fake.counts.get("auth", 0)
    out = rt.call_with_retry(lambda: gen(base_url, "auth"), rt.RetryPolicy(), sleep=c2.sleep, clock=c2.now)
    assert out.gave_up == "not_retryable" and c2.sleeps == [] and _Fake.counts["auth"] - before == 1
