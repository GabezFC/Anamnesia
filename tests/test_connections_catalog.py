"""Connections catalog: validation, shipped file, extensibility without code."""
from __future__ import annotations

import pytest

from app.connections import catalog
from app.connections.catalog import CatalogError, detect, get_connection, load_catalog
from app.connections.snippets import build_snippet

VALID = """connections:
  - id: foo
    type: model
    name: Foo
    command: null
    env_keys: [FOO_API_KEY]
    docs_url: null
    status: planned
    mcp_snippet: null
"""


def _write(tmp_path, text):
    p = tmp_path / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_shipped_catalog_contents():
    entries = {c.id: c for c in load_catalog()}
    assert {"hermes", "claude-code", "codex", "opencode", "anthropic", "openai", "ollama",
            "openrouter", "huggingface", "nvidia", "memory-gateway"} <= set(entries)
    for cid in ("openrouter", "huggingface", "nvidia"):
        assert entries[cid].status == "planned"
    assert entries["memory-gateway"].type == "mcp"
    assert entries["memory-gateway"].command == "python -m app.mcp.server"
    assert entries["anthropic"].env_keys == ("ANTHROPIC_API_KEY",)


@pytest.mark.parametrize("mutate,msg", [
    (lambda t: t.replace("type: model", "type: banana"), "type must be"),
    (lambda t: t.replace("status: planned", "status: weird"), "status must be"),
    (lambda t: t.replace("[FOO_API_KEY]", "[foo_key]"), "env_keys"),
    (lambda t: t.replace("id: foo\n", ""), "missing or invalid field 'id'"),
    (lambda t: t.replace("mcp_snippet: null", "mcp_snippet: nope"), "mcp_snippet"),
    (lambda t: t.replace("docs_url: null", "docs_url: ftp://x"), "docs_url"),
    (lambda t: t + VALID.split("connections:\n")[1], "duplicate connection id"),
    (lambda t: "connections:\n", "non-empty"),
])
def test_validation_errors(tmp_path, mutate, msg):
    with pytest.raises(CatalogError, match=msg):
        load_catalog(_write(tmp_path, mutate(VALID)))


def test_valid_custom_catalog_loads(tmp_path):
    (c,) = load_catalog(_write(tmp_path, VALID))
    assert c.id == "foo" and c.env_keys == ("FOO_API_KEY",) and c.status == "planned"


def test_adding_entry_needs_no_code(tmp_path):
    text = VALID + VALID.split("connections:\n")[1].replace("id: foo", "id: bar").replace("Foo", "Bar")
    cs = load_catalog(_write(tmp_path, text))
    assert [c.id for c in cs] == ["foo", "bar"]
    assert get_connection("bar", tmp_path / "c.yaml").name == "Bar"
    assert build_snippet(cs[1])["status"] == "unverified"


def test_detect_by_env_only(monkeypatch):
    c = get_connection("openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert detect(c) is False
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert detect(c) is True


def test_snippets_confirmed_and_unverified():
    h = build_snippet(get_connection("hermes"))
    assert h["status"] == "ok" and "mcp_servers:" in h["content"] and "app.mcp.server" in h["content"]
    cc = build_snippet(get_connection("claude-code"))
    assert '"mcpServers"' in cc["content"]
    cx = build_snippet(get_connection("codex"))
    assert "[mcp_servers.memory-gateway]" in cx["content"]
    oc = build_snippet(get_connection("opencode"))
    assert oc["status"] == "unverified" and oc["note"] and "content" not in oc
    assert build_snippet(get_connection("anthropic"))["status"] == "unverified"
    mg = build_snippet(get_connection("memory-gateway"))
    assert set(mg["snippets"]) == {"hermes_yaml", "claude_json", "codex_toml"}


def test_catalog_path_is_module_level(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "CATALOG_PATH", _write(tmp_path, VALID))
    assert [c.id for c in load_catalog()] == ["foo"]
