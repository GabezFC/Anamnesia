"""Configuração guiada do JEV (app/services/jev_setup.py + /api/jev/*). Sem rede: backends falsos."""
import logging

import pytest

from app.database.db import Database
from app.services import jev_setup as js

SECRET = "tsk_SUPERSECRET_1234567890abcd"
ENV_KEYS = ["TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "JEV_MODEL", "JEV_MODE", "JEV_RELEVANCE_THRESHOLD",
            "JEV_REVIEW_THRESHOLD", "JEV_INJECTION_THRESHOLD", "JEV_REVIEW_ACTION", "JEV_FAILURE_MODE",
            "JEV_SECOND_PASS", "JEV_CONTRADICTION_CHECK", "JEV_TIMEOUT_S", "JEV_MAX_RETRIES",
            "JEV_MAX_CONCURRENT_REQUESTS", "JEV_BACKEND", "OFFLINE", "ANAMNESIA_PAID_CALLS"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / ".env"
    monkeypatch.setattr(js.security, "ENV_PATH", path)
    db = Database(str(tmp_path / "t.db"))
    yield path, db
    for k in ENV_KEYS:   # save() escreve em os.environ direto
        monkeypatch.delenv(k, raising=False)


def _text(path):
    return path.read_text(encoding="utf-8") if path.exists() else ""


class _StatusErr(Exception):
    def __init__(self, status):
        super().__init__(f"{status} boom")
        self.status = status


class FakeBackend:
    def __init__(self, exc=None, value=0.9):
        self.exc, self.value = exc, value

    def evaluate(self, state, questions):
        if self.exc:
            raise self.exc
        return {"rel_0": self.value}, {"input_tokens": 1, "output_tokens": 1}, "jev-1.13.0"


# 1 + 8: não configurado -> configura; repetir é idempotente
def test_unconfigured_then_configure_and_idempotent(env):
    path, db = env
    assert js.status(db)["state"] == "not_configured"
    r1 = js.save({"model": "jev-1.13.0", "base_url": "https://api.typesafe.ai"}, api_key=SECRET, db=db, env_path=path)
    assert "api_key" in r1["changed"]
    assert r1["status"]["state"] == "configured" and r1["status"]["key_present"]
    before = _text(path)
    r2 = js.save({"model": "jev-1.13.0"}, api_key=SECRET, db=db, env_path=path)
    assert r2["changed"] == [] and "api_key" in r2["unchanged"]
    assert _text(path) == before
    assert _text(path).count("TYPESAFE_API_KEY") == 1


# 5 + 6: parcial / avançado existente nunca é sobrescrito sem pedido; o resto do .env fica intacto
def test_partial_and_advanced_preserved(env):
    path, db = env
    path.write_text("# meu env\nOTHER=1\nJEV_RELEVANCE_THRESHOLD=0.9\nJEV_REVIEW_THRESHOLD=0.6\n", encoding="utf-8")
    import os
    os.environ["JEV_RELEVANCE_THRESHOLD"] = "0.9"
    os.environ["JEV_REVIEW_THRESHOLD"] = "0.6"
    r = js.save({}, api_key=SECRET, db=db, env_path=path)   # só a chave
    assert r["changed"] == ["api_key"]
    txt = _text(path)
    assert "JEV_RELEVANCE_THRESHOLD=0.9" in txt and "OTHER=1" in txt and "# meu env" in txt
    assert "relevance_threshold" in r["status"]["customized"]


def test_invalid_input_rejected_and_nothing_written(env):
    path, db = env
    for bad in [{"base_url": "http://evil.example.com"}, {"base_url": "https://u:p@x.com"},
                {"base_url": "ftp://x.com"}, {"model": "a b; rm -rf"}, {"relevance_threshold": 2},
                {"timeout_s": 99999}, {"mode": "turbo"}, {"unknown_field": 1}, {"second_pass": "yes"}]:
        with pytest.raises(js.JevSetupError):
            js.save(bad, db=db, env_path=path)
    with pytest.raises(js.JevSetupError):   # review > relevance
        js.save({"review_threshold": 0.95}, db=db, env_path=path)
    with pytest.raises(js.JevSetupError):
        js.save({}, api_key="abc\nINJECT=1", db=db, env_path=path)
    assert _text(path) == ""
    js.save({"base_url": "http://127.0.0.1:9999"}, db=db, env_path=path)   # loopback http é permitido


# 3, 4, 7: teste de conexão
def test_connection_success_updates_status(env):
    path, db = env
    js.save({}, api_key=SECRET, db=db, env_path=path)
    res = js.test_connection(db, backend_factory=lambda cfg: FakeBackend())
    assert res["ok"] and res["state"] == "connected" and res["http_status"] == 200
    assert js.status(db)["state"] == "connected"
    js.save({"model": "outro-modelo"}, db=db, env_path=path)   # mudou a config: resultado antigo não vale
    assert js.status(db)["state"] == "configured"


def test_connection_auth_error(env):
    path, db = env
    js.save({}, api_key=SECRET, db=db, env_path=path)
    res = js.test_connection(db, backend_factory=lambda cfg: FakeBackend(_StatusErr(401)))
    assert not res["ok"] and res["state"] == "auth_error" and res["http_status"] == 401
    assert "inválido" in res["message"]
    assert js.status(db)["state"] == "auth_error"


def test_connection_endpoint_unavailable(env):
    path, db = env
    js.save({}, api_key=SECRET, db=db, env_path=path)

    class ConnectError(ConnectionError):
        pass
    res = js.test_connection(db, backend_factory=lambda cfg: FakeBackend(ConnectError("dns")))
    assert res["state"] == "unavailable" and res["http_status"] is None and "alcançar" in res["message"]
    assert js.test_connection(db, backend_factory=lambda c: FakeBackend(_StatusErr(503)))["state"] == "unavailable"


def test_connection_without_key_and_bad_response(env):
    path, db = env
    assert js.test_connection(db, backend_factory=lambda c: FakeBackend())["state"] == "not_configured"
    js.save({}, api_key=SECRET, db=db, env_path=path)
    assert js.test_connection(db, backend_factory=lambda c: FakeBackend(value=5))["state"] == "unavailable"


def test_offline_blocks_remote_test(env, monkeypatch):
    path, db = env
    js.save({}, api_key=SECRET, db=db, env_path=path)
    monkeypatch.setenv("OFFLINE", "1")
    assert js.status(db)["state"] == "blocked"
    assert js.test_connection(db, backend_factory=lambda c: FakeBackend())["state"] == "blocked"


# 9 + 10: segredo nunca em logs / respostas / arquivos versionados
def test_secret_never_leaks(env, caplog):
    path, db = env
    caplog.set_level(logging.DEBUG)
    js.save({"model": "m1"}, api_key=SECRET, db=db, env_path=path)
    js.test_connection(db, backend_factory=lambda c: FakeBackend(_StatusErr(401)))
    st = js.status(db)
    assert SECRET not in repr(st) and SECRET not in caplog.text
    assert st["key_masked"].endswith(SECRET[-4:]) and SECRET not in st["key_masked"]
    assert SECRET in _text(path)   # único lugar: o .env local (ignorado pelo git)


def test_env_file_is_gitignored():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=root)
    assert r.returncode == 0
    ex = (root / ".env.example").read_text(encoding="utf-8")
    assert "TYPESAFE_API_KEY=" in ex and "tsk_" not in ex


# API
def test_api_endpoints(tmp_path, monkeypatch, env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import workspace as ws
    from app.core.state import STATE
    from app.services.security import get_or_create_local_token

    class GW:
        db = env[1]
        jev_cfg = None
        jev = None

        def make_jev(self, cfg):
            return ("jev", cfg.model)

    gw = GW()
    old = STATE.gateway
    STATE.gateway = gw
    app = FastAPI()
    app.include_router(ws.router)
    c = TestClient(app, client=("127.0.0.1", 50000), headers={"X-MG-Token": get_or_create_local_token()})
    try:
        assert c.get("/api/jev/status").json()["state"] == "not_configured"
        r = c.post("/api/jev/config", json={"settings": {"model": "jev-x"}, "api_key": SECRET},
                   headers={"Origin": "http://testserver", "Referer": "http://testserver/"})
        assert r.status_code == 200, r.text
        assert SECRET not in r.text
        assert gw.jev == ("jev", "jev-x")   # gateway em execução recarregado
        bad = c.post("/api/jev/config", json={"settings": {"base_url": "http://evil.com"}},
                     headers={"Origin": "http://testserver", "Referer": "http://testserver/"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_field"
        noauth = TestClient(app, client=("127.0.0.1", 50000)).post("/api/jev/test")
        assert noauth.status_code == 403
    finally:
        STATE.gateway = old
