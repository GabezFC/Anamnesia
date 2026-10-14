"""Vault scaffold: creates the standard folder layout, never overwrites, stays inside the vault."""
from __future__ import annotations

import pytest

from app.memory_store import vault_scaffold as vs
from tests.test_api_mcp import client  # noqa: F401


def test_scaffold_creates_layout_and_templates(tmp_path):
    out = vs.scaffold(tmp_path)
    assert "00-Inbox" in out["created"] and "99-Templates/_nota.md" in out["created"]
    for rel in vs.FOLDERS:
        assert (tmp_path / rel).is_dir()
    assert "{{title}}" in (tmp_path / "99-Templates" / "_nota.md").read_text(encoding="utf-8")


def test_scaffold_is_idempotent_and_never_overwrites(tmp_path):
    (tmp_path / "99-Templates").mkdir()
    (tmp_path / "99-Templates" / "_nota.md").write_text("MEU", encoding="utf-8")
    vs.scaffold(tmp_path)
    assert (tmp_path / "99-Templates" / "_nota.md").read_text(encoding="utf-8") == "MEU"
    again = vs.scaffold(tmp_path)
    assert again["created"] == []


def test_dry_run_writes_nothing(tmp_path):
    out = vs.scaffold(tmp_path, dry_run=True)
    assert out["created"] and not any(tmp_path.iterdir())


def test_project_scaffold_and_bad_names(tmp_path):
    out = vs.scaffold_project(tmp_path, "Meu Projeto")
    assert (tmp_path / "30-Projetos" / "Meu Projeto" / "Notes" / "Daily").is_dir() and len(out["created"]) == 4
    for bad in ("..", "a/b", "", "x:y"):
        with pytest.raises(ValueError):
            vs.scaffold_project(tmp_path, bad)


def test_missing_root_is_rejected(tmp_path):
    with pytest.raises(NotADirectoryError):
        vs.scaffold(tmp_path / "nope")


def test_endpoint_dry_run_and_apply(client, tmp_path):  # noqa: F811
    tmp_path = tmp_path / "scaffold_target"          # the fixture's benchmark.db lives in tmp_path itself
    tmp_path.mkdir()
    r = client.post("/config/vault-scaffold", json={"path": str(tmp_path), "dry_run": True})
    assert r.status_code == 200, r.text
    assert not any(tmp_path.iterdir())
    r = client.post("/config/vault-scaffold", json={"path": str(tmp_path), "project": "Demo"})
    assert r.status_code == 200 and (tmp_path / "70-Daily").is_dir()
    assert (tmp_path / "30-Projetos" / "Demo" / "Notes" / "Notas").is_dir()


def test_endpoint_rejects_missing_dir(client, tmp_path):  # noqa: F811
    assert client.post("/config/vault-scaffold", json={"path": str(tmp_path / "x")}).status_code == 422
