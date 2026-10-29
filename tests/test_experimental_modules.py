"""B3b: modulos EXPERIMENTAIS mantidos fora do fluxo real -- import, marcacao e CLI do catalogo."""
from __future__ import annotations

import importlib
import json

import pytest

from app.memory_store import catalog
from app.memory_store.store import SavedContextStore

EXPERIMENTAL = ("app.memory_store.catalog", "app.routing.ab", "app.routing.task_router", "app.services.context_plan")


@pytest.mark.parametrize("name", EXPERIMENTAL)
def test_experimental_module_imports_and_is_marked(name):
    mod = importlib.import_module(name)
    assert "EXPERIMENTAL" in (mod.__doc__ or "")


def test_catalog_cli_stats_rebuild_verify_work_standalone(tmp_path, capsys):
    root = tmp_path / "saved_context"
    store = SavedContextStore(root)
    store.save(title="Nota catalogo", content="conteudo de teste do catalogo", project="anamnesia")
    assert not hasattr(store, "catalog")  # not wired: the CLI must not depend on it
    assert catalog.main(["stats", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["scanned"] == 1
    assert catalog.main(["rebuild", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["reparsed"] == 1
    assert catalog.main(["verify", "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
