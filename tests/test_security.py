"""Local-only write protection (§5.4, §3 da proposta 2026-09-28). No network, no real .env touched
(see tests/conftest.py:_isolated_local_files, which redirects app.services.security.ENV_PATH).
"""
from __future__ import annotations

import os

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.services import security


@pytest.fixture
def guarded_app():
    app = FastAPI()

    @app.get("/open")
    def open_read():
        return {"ok": True}

    @app.get("/bootstrap", dependencies=[Depends(security.require_localhost)])
    def bootstrap():
        return {"ok": True}

    @app.post("/write", dependencies=[Depends(security.require_local_write)])
    def write():
        return {"ok": True}

    return app


def local_client(app, **kw) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 51234), **kw)


def remote_client(app, **kw) -> TestClient:
    return TestClient(app, client=("192.168.1.50", 51234), **kw)


# -- get_or_create_local_token ------------------------------------------------------------------
def test_token_generated_once_and_persisted(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(security, "ENV_PATH", env_path)
    t1 = security.get_or_create_local_token()
    t2 = security.get_or_create_local_token()
    assert t1 == t2
    assert len(t1) >= 32
    assert f"MG_LOCAL_TOKEN={t1}" in env_path.read_text(encoding="utf-8")
    assert os.environ["MG_LOCAL_TOKEN"] == t1


def test_token_write_preserves_other_env_lines(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("MEMORY_GATEWAY_VAULT=./data/synthetic_vault\nANTHROPIC_API_KEY=sk-existing\n",
                        encoding="utf-8")
    monkeypatch.setattr(security, "ENV_PATH", env_path)
    security.get_or_create_local_token()
    text = env_path.read_text(encoding="utf-8")
    assert "MEMORY_GATEWAY_VAULT=./data/synthetic_vault" in text
    assert "ANTHROPIC_API_KEY=sk-existing" in text
    assert text.count("MG_LOCAL_TOKEN=") == 1


def test_token_reused_from_environ_without_touching_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    monkeypatch.setattr(security, "ENV_PATH", env_path)
    monkeypatch.setenv("MG_LOCAL_TOKEN", "already-set-token")
    assert security.get_or_create_local_token() == "already-set-token"
    assert not env_path.exists()


# -- mask_secret ----------------------------------------------------------------------------------
@pytest.mark.parametrize("value,expected_suffix", [("sk-ant-abcd1234", "1234"), ("abcd", "abcd")])
def test_mask_secret_shows_only_last_four(value, expected_suffix):
    masked = security.mask_secret(value)
    assert masked.endswith(expected_suffix)
    assert value not in masked or value == expected_suffix
    assert masked != value


def test_mask_secret_none_for_empty():
    assert security.mask_secret(None) is None
    assert security.mask_secret("") is None


def test_mask_secret_does_not_reveal_real_length_relationship():
    short = security.mask_secret("abcd")
    long = security.mask_secret("x" * 40 + "abcd")
    assert short.endswith("abcd") and long.endswith("abcd")
    # both masks use the SAME fixed prefix length regardless of the real secret's length
    assert len(short) == len(long)


# -- require_localhost ----------------------------------------------------------------------------
def test_require_localhost_allows_loopback(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    assert local_client(guarded_app).get("/bootstrap").status_code == 200


def test_require_localhost_rejects_remote_ip(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    r = remote_client(guarded_app).get("/bootstrap")
    assert r.status_code == 403


# -- require_local_write ---------------------------------------------------------------------------
def test_require_local_write_rejects_non_local_ip(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    token = security.get_or_create_local_token()
    r = remote_client(guarded_app, headers={"X-MG-Token": token}).post("/write")
    assert r.status_code == 403
    assert "127.0.0.1" in r.json()["detail"]


def test_require_local_write_rejects_missing_token(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    r = local_client(guarded_app).post("/write")
    assert r.status_code == 403
    assert "Token" in r.json()["detail"]


def test_require_local_write_rejects_wrong_token(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    security.get_or_create_local_token()
    r = local_client(guarded_app, headers={"X-MG-Token": "not-the-token"}).post("/write")
    assert r.status_code == 403


def test_require_local_write_accepts_local_with_valid_token_and_no_origin(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    token = security.get_or_create_local_token()
    r = local_client(guarded_app, headers={"X-MG-Token": token}).post("/write")
    assert r.status_code == 200


def test_require_local_write_accepts_matching_origin(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    token = security.get_or_create_local_token()
    c = local_client(guarded_app, headers={"X-MG-Token": token})
    r = c.post("/write", headers={"Origin": "http://testserver"})
    assert r.status_code == 200


def test_require_local_write_rejects_foreign_origin(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    token = security.get_or_create_local_token()
    c = local_client(guarded_app, headers={"X-MG-Token": token})
    r = c.post("/write", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert "Origin" in r.json()["detail"]


def test_require_local_write_rejects_foreign_referer(guarded_app, tmp_path, monkeypatch):
    monkeypatch.setattr(security, "ENV_PATH", tmp_path / ".env")
    token = security.get_or_create_local_token()
    c = local_client(guarded_app, headers={"X-MG-Token": token})
    r = c.post("/write", headers={"Referer": "http://evil.example/page"})
    assert r.status_code == 403
    assert "Referer" in r.json()["detail"]


def test_open_endpoint_needs_no_guard(guarded_app):
    assert remote_client(guarded_app).get("/open").status_code == 200
