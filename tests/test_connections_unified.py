"""Sub-aba Chaves removida, OpenCode sem chaves duplicadas, estados verídicos de conexão."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.connections import router
from app.services.security import get_or_create_local_token

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "frontend" / "js"
NODE = shutil.which("node") is not None
FAKE = "sk-tes...cdef"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_ALLOW_NETWORK_TEST", raising=False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, client=("127.0.0.1", 51234), headers={"X-MG-Token": get_or_create_local_token()})


def _items(c):
    return {i["id"]: i for i in c.get("/api/connections").json()["connections"]}


def test_opencode_has_no_own_key_fields(client):
    oc = _items(client)["opencode"]
    assert oc["env_keys"] == [] and oc["keys"] == {}
    assert set(oc["uses_providers"]) >= {"anthropic", "openai", "openrouter"}


def test_single_openrouter_provider_entry(client):
    items = _items(client)
    owners = [i for i in items.values() if i["type"] == "model" and "OPENROUTER_API_KEY" in i["env_keys"]]
    assert [o["id"] for o in owners] == ["openrouter"]
    assert items["openrouter"]["type"] == "model" and items["openrouter"]["status"] == "available"


def test_provider_credential_save_remove_and_never_exposed(client):
    r = client.put("/api/connections/openrouter/secret", json={"env_key": "OPENROUTER_API_KEY", "value": FAKE})
    assert r.status_code == 200 and FAKE not in r.text
    assert FAKE not in client.get("/api/connections").text
    # o agente reaproveita a mesma credencial, sem cópia
    from app.connections import secrets
    assert secrets.resolve_env(["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"]).get("OPENROUTER_API_KEY") == FAKE
    d = client.request("DELETE", "/api/connections/openrouter/secret", json={"env_key": "OPENROUTER_API_KEY"})
    assert d.status_code == 200 and FAKE not in d.text
    assert "OPENROUTER_API_KEY" not in secrets.resolve_env(["OPENROUTER_API_KEY"])


def test_path_detection_is_not_connected(client, monkeypatch):
    from app.connections import verify
    monkeypatch.setattr(verify.shutil, "which", lambda c: f"/bin/{c}")
    st = _items(client)["opencode"]["state"]
    assert st in {"detected", "configured"} and st != "connected"
    t = client.post("/api/connections/opencode/test").json()
    assert t["state"] != "connected" and t["ok"] is False


def test_missing_binary_is_not_installed(client, monkeypatch):
    from app.connections import verify
    monkeypatch.setattr(verify.shutil, "which", lambda c: None)
    assert _items(client)["opencode"]["state"] == "not_installed"


def test_no_demo_connection_seeds():
    t = (JS / "mock-data.js").read_text(encoding="utf-8")
    assert "export const mockConnections = { agents: [], models: [], mcp: [] };" in t


def test_keys_tab_removed_from_sources():
    cfg = (JS / "pages" / "config.js").read_text(encoding="utf-8")
    i18n = (JS / "i18n-config.js").read_text(encoding="utf-8")
    assert "renderKeysTab" not in cfg and "['keys'" not in cfg and "t.tabKeys" not in cfg
    for k in ("tabKeys", "keysTitle", "keysDesc", "keysEmpty"):
        assert k not in i18n
    assert "aba Chaves" not in i18n and "Keys tab" not in i18n


def _node(code: str) -> str:
    r = subprocess.run(["node", "--input-type=module", "-e", code], cwd=str(JS), capture_output=True,
                       text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


STUBS = """
const store = {};
globalThis.localStorage = { getItem(k){return k in store ? store[k] : null}, setItem(k,v){store[k]=String(v)}, removeItem(k){delete store[k]} };
globalThis.window = { addEventListener(){}, dispatchEvent(){} };
globalThis.CustomEvent = class { constructor(n, o){ this.type = n; this.detail = o && o.detail; } };
globalThis.document = { documentElement: { setAttribute(){} } };
"""


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_config_dom_no_keys_tab_and_legacy_redirect():
    out = _node(STUBS + """
const m = await import('./pages/config.js');
m.setDebugState('loaded');
const h = m.render();
console.log(JSON.stringify({ keys: h.includes('data-tab="keys"'), pw: h.includes('save-key'),
  legacy: [m.isLegacyKeysHash('#/config/keys'), m.isLegacyKeysHash('#/config?tab=keys'), m.isLegacyKeysHash('#/config'), m.isLegacyKeysHash('#/connections')] }));
""")
    import json
    d = json.loads(out.splitlines()[-1])
    assert d == {"keys": False, "pw": False, "legacy": [True, True, False, False]}, d


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_connections_dom_opencode_no_key_inputs_and_provider_inputs_typeable():
    out = _node(STUBS + """
const md = await import('./mock-data.js');
const m = await import('./pages/connections.js');
md.mockConnections.agents = [{ id:'opencode', name:'OpenCode', type:'Agente CLI', detected:true, has_key:false, env_keys:[], uses_providers:['anthropic','openai','openrouter'], state:'detected', state_detail:'', status:'offline' }];
md.mockConnections.models = ['anthropic:ANTHROPIC_API_KEY','openai:OPENAI_API_KEY','openrouter:OPENROUTER_API_KEY'].map(s => { const [id,k]=s.split(':'); return { id, name:id, type:'Provedor de modelo', detected:false, has_key:false, env_keys:[k], state:'not_configured', state_detail:'', status:'offline' }; });
const html = m.render();
const card = (id) => { const a = html.indexOf('data-connection-id="'+id+'"'); const b = html.indexOf('data-connection-id=', a+10); return html.slice(a, b<0?undefined:b); };
const inputs = (h) => (h.match(/<input[^>]*type="password"[^>]*>/g) || []);
const names = [...html.matchAll(/<input[^>]*data-env-key="([A-Z_]+)"/g)].map(x => x[1]);
console.log(JSON.stringify({ oc: inputs(card('opencode')).length, ocUses: card('opencode').includes('uses-providers'),
  ocDisabled: /readonly|disabled/.test(inputs(card('anthropic'))[0] || ''),
  names, chip: card('opencode').includes('Detectado') }));
""")
    import json
    d = json.loads(out.splitlines()[-1])
    assert d["oc"] == 0 and d["ocUses"] and not d["ocDisabled"] and d["chip"], d
    assert sorted(d["names"]) == sorted(set(d["names"])) and len(d["names"]) == 3, d
