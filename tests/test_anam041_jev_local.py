"""ANAM-041: TYPESAFE_BASE_URL em loopback (Colibrì /v1/systemone) — sem chave real, egress local, fail-closed.
Servidor HTTP falso em thread no formato de docs/systemone.md do Colibrì (o Colibrì real NÃO é iniciado)."""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("typesafe_sdk")
from app.services import jev_setup as js  # noqa: E402
from app.services.egress import EgressBlocked, check_egress  # noqa: E402
from app.services.jev import (TypeSafeBackend, is_local_base_url, LOCAL_KEY_DEFAULT)  # noqa: E402
from config.jev import JevConfig  # noqa: E402

ENV = ["TYPESAFE_API_KEY", "TYPESAFE_LOCAL_API_KEY", "TYPESAFE_BASE_URL", "JEV_FAILURE_MODE", "OFFLINE",
       "ANAMNESIA_PAID_CALLS", "ANAMNESIA_EGRESS_ALLOW_HOSTS", "JEV_BACKEND"]


class _H(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"object": "list", "data": [{"id": "qwen36", "object": "model"}],
                    "models": [{"name": "jev-latest", "description": "Colibri", "release_date": "2026-01-01"}]})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        _H.seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                        "xkey": self.headers.get("x-api-key"), "req": req})
        answers = {k: {"type": "noul", "noul": 0.8476} for k in req.get("questions", {})}
        self._send({"id": "req_1", "model": "qwen36", "provider": "colibri", "answers": answers,
                    "usage": {"input_tokens": 86, "output_tokens": 15, "cost": 0}})


@pytest.fixture
def server(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    _H.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("TYPESAFE_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    yield srv
    srv.shutdown()
    srv.server_close()


QS = {"rel_0": {"instructions": "Does it help?", "criteria": {"true": "yes", "false": "no"}}}


def _cfg():
    return JevConfig(max_retries=0, timeout_s=5.0)


def test_local_backend_without_real_key(server):
    b = TypeSafeBackend(_cfg())
    answers, usage, model = b.evaluate({"query": "q"}, QS)
    assert answers == {"rel_0": pytest.approx(0.8476)}
    assert usage == {"input_tokens": 86, "output_tokens": 15} and model == "qwen36"
    seen = _H.seen[0]
    assert seen["path"] == "/v1/systemone"
    assert LOCAL_KEY_DEFAULT in (seen["auth"] or "") + (seen["xkey"] or "")
    assert seen["req"]["questions"]["rel_0"]["type"] == "noul"
    b.close()


def test_local_key_optional_override(server, monkeypatch):
    monkeypatch.setenv("TYPESAFE_LOCAL_API_KEY", "minha-chave-local")
    TypeSafeBackend(_cfg()).evaluate({"query": "q"}, QS)
    assert "minha-chave-local" in (_H.seen[0]["auth"] or "") + (_H.seen[0]["xkey"] or "")


def test_local_defaults_fail_closed_and_env_override(server, monkeypatch):
    cfg = _cfg()
    cfg.failure_mode = "fail_open"
    TypeSafeBackend(cfg)
    assert cfg.failure_mode == "fail_closed"
    monkeypatch.setenv("JEV_FAILURE_MODE", "fail_open")
    cfg2 = _cfg()
    cfg2.failure_mode = "fail_open"
    TypeSafeBackend(cfg2)
    assert cfg2.failure_mode == "fail_open"   # escolha explícita do usuário é respeitada


def test_server_down_raises_and_unjudged_does_not_survive(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()   # porta fechada: nada escutando
    monkeypatch.setenv("TYPESAFE_BASE_URL", f"http://127.0.0.1:{port}")
    from app.services.jev import UNJUDGED, survives
    cfg = _cfg()
    b = TypeSafeBackend(cfg)
    with pytest.raises(Exception):
        b.evaluate({"query": "q"}, QS)
    assert survives(UNJUDGED, cfg) is False


def test_egress_loopback_is_local_not_remote(server, monkeypatch):
    check_egress(f"http://127.0.0.1:{server.server_port}", "typesafe")
    with pytest.raises(EgressBlocked):
        check_egress("http://192.168.0.5:8000", "typesafe")   # http fora de loopback segue recusado
    with pytest.raises(EgressBlocked):
        check_egress("https://evil.example.com", "typesafe")
    monkeypatch.setenv("OFFLINE", "1")   # modo offline: loopback continua permitido, remoto não
    check_egress(f"http://localhost:{server.server_port}", "typesafe")
    with pytest.raises(Exception):
        check_egress("https://api.typesafe.ai", "typesafe")
    assert is_local_base_url("http://localhost:8000") and not is_local_base_url("https://api.typesafe.ai")


def test_remote_still_requires_key(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    assert js.test_connection()["state"] == "not_configured"   # default api.typesafe.ai sem chave


def test_setup_status_and_test_connection_local(server, monkeypatch):
    st = js.status()
    assert st["local"] is True and st["state"] != "not_configured"
    res = js.test_connection()
    assert res["ok"] is True and res["state"] == "connected", res
    assert any(r["path"] == "/v1/systemone" for r in _H.seen)
