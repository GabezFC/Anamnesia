"""Connections REST API: guarded secret writes, masked listing, offline test, snippets."""
from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.connections import router
from app.services.security import get_or_create_local_token

FAKE = "sk-test-1234567890abcdef"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_ALLOW_NETWORK_TEST", raising=False)
    app = FastAPI()
    app.include_router(router)
    token = get_or_create_local_token()
    tc = TestClient(app, client=("127.0.0.1", 51234), headers={"X-MG-Token": token})
    tc.anon = TestClient(app, client=("127.0.0.1", 51234))
    return tc


def _put(c, cid="anthropic", key="ANTHROPIC_API_KEY", value=FAKE):
    return c.put(f"/api/connections/{cid}/secret", json={"env_key": key, "value": value})


def _delete(c, cid="anthropic", key="ANTHROPIC_API_KEY"):
    return c.request("DELETE", f"/api/connections/{cid}/secret", json={"env_key": key})


def test_list_has_all_entries_and_no_secret(client):
    r = client.get("/api/connections")
    assert r.status_code == 200
    items = {c["id"]: c for c in r.json()["connections"]}
    assert {"hermes", "anthropic", "openrouter", "memory-gateway"} <= set(items)
    a = items["anthropic"]
    assert a["has_key"] is False and a["masked"] is None and a["detected"] is False
    assert items["memory-gateway"]["detected"] is True


def test_secret_roundtrip_never_leaks(client, caplog):
    caplog.set_level(logging.DEBUG)
    bodies = []
    r = _put(client)
    bodies.append(r.text)
    assert r.status_code == 200 and r.json()["has_key"] is True
    assert r.json()["masked"].endswith("cdef")
    lst = client.get("/api/connections")
    bodies.append(lst.text)
    a = next(c for c in lst.json()["connections"] if c["id"] == "anthropic")
    assert a["has_key"] is True and a["masked"].endswith("cdef") and a["detected"] is True
    bodies.append(client.post("/api/connections/anthropic/test").text)
    bodies.append(client.get("/api/connections/anthropic/snippet").text)
    for b in bodies:
        assert FAKE not in b and "sk-test" not in b
    assert FAKE not in caplog.text
    d = _delete(client)
    bodies.append(d.text)
    assert d.status_code == 200 and d.json()["removed"] is True and d.json()["has_key"] is False
    assert FAKE not in d.text
    after = next(c for c in client.get("/api/connections").json()["connections"] if c["id"] == "anthropic")
    assert after["has_key"] is False


def test_403_without_token(client):
    assert client.anon.put("/api/connections/anthropic/secret",
                           json={"env_key": "ANTHROPIC_API_KEY", "value": FAKE}).status_code == 403
    assert client.anon.request("DELETE", "/api/connections/anthropic/secret",
                               json={"env_key": "ANTHROPIC_API_KEY"}).status_code == 403
    assert client.anon.post("/api/connections/anthropic/test").status_code == 403
    assert client.get("/api/connections").json()["connections"][0]  # nothing stored
    assert not any(c["has_key"] for c in client.get("/api/connections").json()["connections"])


def test_403_non_loopback(client):
    app = client.app
    remote = TestClient(app, client=("10.1.2.3", 5), headers=dict(client.headers))
    assert remote.put("/api/connections/anthropic/secret",
                      json={"env_key": "ANTHROPIC_API_KEY", "value": FAKE}).status_code == 403


def test_unknown_env_key_and_unknown_connection(client):
    r = _put(client, key="OPENAI_API_KEY")  # valid key name, wrong connection
    assert r.status_code == 400 and FAKE not in r.text
    assert _put(client, key="MG_LOCAL_TOKEN").status_code == 400
    assert _delete(client, key="MG_LOCAL_TOKEN").status_code == 400
    assert _put(client, cid="nope").status_code == 404
    assert _put(client, cid="hermes", key="X").status_code == 400  # no env_keys
    assert client.get("/api/connections/nope/snippet").status_code == 404


def test_empty_value_rejected(client):
    assert _put(client, value="   ").status_code == 400


def test_snippet_ok_and_unverified(client):
    ok = client.get("/api/connections/codex/snippet").json()
    assert ok["status"] == "ok" and "[mcp_servers.memory-gateway]" in ok["content"]
    un = client.get("/api/connections/opencode/snippet").json()
    assert un["status"] == "unverified" and un["note"]


def test_test_endpoint_is_offline_by_default(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr("app.api.connections.urllib.request.urlopen", boom)
    r = client.post("/api/connections/ollama/test")
    assert r.status_code == 200 and r.json()["network_checked"] is False
    r = client.post("/api/connections/openai/test")
    body = r.json()
    assert body["network_checked"] is False and body["ok"] is False
    assert any(c["name"] == "env:OPENAI_API_KEY" and not c["ok"] for c in body["checks"])
    _put(client, "openai", "OPENAI_API_KEY")
    assert client.post("/api/connections/openai/test").json()["ok"] is True


def test_network_flag_only_probes_ollama(client, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_ALLOW_NETWORK_TEST", "1")
    monkeypatch.setattr("app.api.connections._ollama_probe", lambda: (True, "HTTP 200"))
    assert client.post("/api/connections/ollama/test").json()["network_checked"] is True
    assert client.post("/api/connections/openai/test").json()["network_checked"] is False
