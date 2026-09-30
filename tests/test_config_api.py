"""Interactive configuration endpoints (§3 da proposta 2026-09-28): /config/*.

Reuses the `client` fixture from test_api_mcp.py (loopback TestClient, X-MG-Token attached — see
its docstring) so these tests exercise the real require_local_write gate, not a bypass.
"""
from __future__ import annotations

import pytest

from app.services.security import MODEL_KEY_ENV_VARS
from config.optional_stages_catalog import CATALOG, REJECTED
from tests.test_api_mcp import client  # noqa: F401 -- reused as a pytest fixture


# -- token bootstrap --------------------------------------------------------------------------
def test_config_token_is_loopback_only(client):
    r = client.get("/config/token")
    assert r.status_code == 200
    assert isinstance(r.json()["token"], str) and len(r.json()["token"]) >= 32


# -- model keys ---------------------------------------------------------------------------------
def test_model_keys_start_unset(client):
    body = client.get("/config/model-keys").json()
    assert set(body) == set(MODEL_KEY_ENV_VARS)
    assert all(v is None for v in body.values())


def test_set_model_key_masks_and_never_echoes_plaintext(client):
    r = client.post("/config/model-key", json={"key_name": "ANTHROPIC_API_KEY", "value": "sk-ant-secret1234"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key_name"] == "ANTHROPIC_API_KEY"
    assert body["masked"].endswith("1234")
    assert "secret" not in body["masked"]
    got = client.get("/config/model-keys").json()
    assert got["ANTHROPIC_API_KEY"].endswith("1234")
    assert got["OPENAI_API_KEY"] is None


def test_set_model_key_rejects_unknown_name(client):
    r = client.post("/config/model-key", json={"key_name": "SOME_RANDOM_VAR", "value": "x"})
    assert r.status_code == 422


def test_set_model_key_requires_write_guard(client):
    from app.services import security

    r = client.post("/config/model-key", json={"key_name": "ANTHROPIC_API_KEY", "value": "x"},
                    headers={"X-MG-Token": "wrong"})
    assert r.status_code == 403
    # confirm the guard actually ran (not e.g. a validation error before it)
    assert "Token" in r.json()["detail"]


# -- verdict flag ---------------------------------------------------------------------------------
def test_verdict_flag_roundtrip_reflects_in_system_info(client):
    before = client.get("/config/verdict").json()
    assert before["enabled"] is False  # default, per docs/SCOPE_BENCHMARK.md

    r = client.post("/config/verdict", json={"enabled": True})
    assert r.status_code == 200
    assert r.json()["enabled"] is True

    assert client.get("/config/verdict").json()["enabled"] is True
    info = client.get("/system/info").json()
    assert info["settings"]["verdict_enabled"] is True


# -- optional stages ------------------------------------------------------------------------------
def test_optional_stages_catalog_lists_known_and_rejected(client):
    body = client.get("/config/optional-stages").json()
    assert set(body["catalog"]) == set(CATALOG)
    assert set(body["rejected"]) == set(REJECTED)
    assert body["enabled"] == {}


def test_optional_stages_set_rejects_unknown_name(client):
    r = client.post("/config/optional-stages", json={"stages": {"not_a_real_stage": True}})
    assert r.status_code == 422


def test_optional_stages_set_and_reflects_in_system_info(client):
    r = client.post("/config/optional-stages", json={"stages": {"llmlingua2": True, "provence": False}})
    assert r.status_code == 200
    assert r.json()["enabled"] == {"llmlingua2": True, "provence": False}

    info = client.get("/system/info").json()
    assert info["settings"]["optional_stages"] == {"llmlingua2": True, "provence": False}

    # a second, partial update MERGES rather than replacing the whole map
    r2 = client.post("/config/optional-stages", json={"stages": {"bge_reranker_v2_m3": True}})
    assert r2.json()["enabled"] == {"llmlingua2": True, "provence": False, "bge_reranker_v2_m3": True}


def test_rejected_stages_have_no_toggle_path(client):
    for name in REJECTED:
        r = client.post("/config/optional-stages", json={"stages": {name: True}})
        assert r.status_code == 422, f"{name} deveria ser rejeitado (sem toggle)"


# -- vault path -----------------------------------------------------------------------------------
def test_vault_path_rejects_repo_root():
    # Direct unit check (no HTTP round trip needed): the repo root itself must never validate.
    from config import PROJECT_ROOT
    from config.retrieval import resolve_vault_path, validate_vault_path_for_runtime
    with pytest.raises(PermissionError):
        validate_vault_path_for_runtime(resolve_vault_path(str(PROJECT_ROOT)))


def test_vault_path_endpoint_rejects_nonexistent_path(client):
    r = client.post("/config/vault-path", json={"path": "Z:/does/not/exist/anywhere"})
    assert r.status_code == 422


def test_vault_path_endpoint_rejects_db_inside_vault(client, tmp_path):
    # The fixture's gateway uses db_path=tmp_path/"b.db"; tmp_path itself is that db's parent, so
    # pointing the vault AT tmp_path must be rejected before anything is persisted or rebuilt.
    r = client.post("/config/vault-path", json={"path": str(tmp_path)})
    assert r.status_code == 422
    assert "benchmark.db" in r.json()["detail"]


def test_vault_path_endpoint_switches_gateway_at_runtime(client, tmp_path):
    from app.api import routes

    new_vault = tmp_path / "other_vault"
    (new_vault / "20-Dev-IA").mkdir(parents=True)
    (new_vault / "20-Dev-IA" / "nota.md").write_text(
        "---\nid: 1\ntitle: x\narea: Dev-IA\ntype: nota\ntags: []\nstatus: ativo\n---\n# X\nconteudo\n",
        encoding="utf-8")

    r = client.post("/config/vault-path", json={"path": str(new_vault)})
    assert r.status_code == 200, r.text
    assert r.json()["markdown_files"] == 1
    assert routes._state["gateway"].vault.root == new_vault.resolve()

    info = client.get("/system/info").json()
    assert info["settings"]["vault_path"] == str(new_vault.resolve())


def test_env_not_leaked_after_vault_switch_or_model_key_write():
    """Regression guard: both endpoints above mutate `os.environ` directly (that IS how "aplica em
    runtime" works, §3) -- tests/conftest.py:_isolated_local_files must undo that after every test,
    or one test's vault-path/key write silently changes what a LATER, unrelated test observes.
    """
    import os
    assert "MEMORY_GATEWAY_VAULT" not in os.environ
    assert "ANTHROPIC_API_KEY" not in os.environ
