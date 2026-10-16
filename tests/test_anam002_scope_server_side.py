"""ANAM-002: REST /memory/search deriva o escopo no servidor; cliente anonimo nao escolhe escopo arbitrario."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.state import STATE
from app.services import security, session_tokens


@pytest.fixture
def seen(monkeypatch):
    out: dict = {}

    class FakeGw:
        def search(self, q, pipeline, n, **kw):
            out["scope"] = kw.get("scope")
            raise RuntimeError("stop")        # basta capturar o escopo
    monkeypatch.setattr(STATE, "gateway", FakeGw())
    monkeypatch.delenv("ANAMNESIA_SCOPE_ANON", raising=False)
    return out


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MG_HOST", "127.0.0.1")
    from app.main import create_app
    return TestClient(create_app(), client=("127.0.0.1", 5000), raise_server_exceptions=False,
                      headers={"Host": "localhost"})


def _tok():
    return {"X-MG-Token": security.get_or_create_local_token()}


def test_anonymous_arbitrary_scope_denied_by_default(client, seen):
    r = client.post("/memory/search", json={"query": "x", "scope": "projeto:segredo"})
    assert r.status_code == 403 and "scope" not in seen


def test_anonymous_without_scope_unchanged(client, seen):
    client.post("/memory/search", json={"query": "x"})
    assert seen["scope"] is None


def test_session_token_overrides_client_scope(client, seen):
    t = session_tokens.mint("projeto:alpha")
    try:
        client.post("/memory/search", json={"query": "x", "scope": "projeto:segredo"}, headers={"X-MG-Session": t})
        assert seen["scope"] == "projeto:alpha"
        client.post("/memory/search", json={"query": "x"}, headers={"X-MG-Session": t})
        assert seen["scope"] == "projeto:alpha"
    finally:
        session_tokens.revoke(t)


def test_trusted_ui_mcp_cli_credential_keeps_scope(client, seen):
    client.post("/memory/search", json={"query": "x", "scope": "projeto:a"}, headers=_tok())
    assert seen["scope"] == "projeto:a"
    client.post("/memory/search", json={"query": "x", "scope": "projeto:b"},
                headers={"Authorization": "Bearer " + security.get_or_create_local_token()})
    assert seen["scope"] == "projeto:b"


def test_wrong_token_is_anonymous(client, seen):
    r = client.post("/memory/search", json={"query": "x", "scope": "projeto:a"}, headers={"X-MG-Token": "errado"})
    assert r.status_code == 403 and "scope" not in seen


@pytest.mark.parametrize("path", ["/memory/search/baseline", "/memory/search/graphify", "/memory/search/graphify-jev"])
def test_variant_routes_share_the_guard(client, seen, path):
    assert client.post(path, json={"query": "x", "scope": "projeto:z"}).status_code == 403


def test_transition_flag_ignore_and_allow(client, seen, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_SCOPE_ANON", "ignore")
    client.post("/memory/search", json={"query": "x", "scope": "projeto:z"})
    assert seen["scope"] is None
    monkeypatch.setenv("ANAMNESIA_SCOPE_ANON", "allow")
    client.post("/memory/search", json={"query": "x", "scope": "projeto:z"})
    assert seen["scope"] == "projeto:z"
