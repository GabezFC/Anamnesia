"""Project identities must never alias through the SavedContextStore length limit."""
import json
from types import SimpleNamespace

import pytest

from app.memory_store.store import SavedContextStore
from app.terminals.projects import ProjectRegistry
from app.workspace_io import tasks
from app.workspace_io.jobs import Job

PREFIX = "p" * 80
LONG_A = PREFIX + "-A"
LONG_B = PREFIX + "-B"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    result = SavedContextStore(tmp_path / "notes", rate_per_min=0)
    monkeypatch.setattr(tasks, "import_store", lambda: result)
    monkeypatch.setattr(tasks, "_after_change", lambda: None)
    return result


def import_notes(notes, project_name=None, apply=True):
    return tasks.run_import([("notes.json", json.dumps(notes))], Job("import", "import", None),
                            apply=apply, project_name=project_name)


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("kind", tasks.EXPORT_KINDS)
def test_registered_long_project_export_fails_closed(store, tmp_path, monkeypatch, kind, apply):
    registry = ProjectRegistry(tmp_path / "registry.db")
    project = registry.add(LONG_A, str(tmp_path))
    assert project.name == LONG_A  # Registry permits this identity; store does not.
    foreign = store.save("Other project's note", "Foreign body", project=PREFIX)
    store._mutate(foreign, feedback_useful=1)
    tasks._atomic_write(tasks.index_path(project.id), json.dumps({
        "version": tasks.INDEX_VERSION, "files": {"main.py": {"size": 1}}
    }).encode())
    monkeypatch.setattr(tasks, "_metrics", lambda _: ({}, []))
    job = Job("export", "export", project.id)
    with pytest.raises(tasks.WorkspaceIOError, match="80") as error:
        tasks.run_export(kind, "json", job, apply=apply, project=project)
    assert error.value.code == "project_name_too_long"
    assert job.artifact is None
    assert len(store.list()) == 1


@pytest.mark.parametrize("apply", [False, True])
def test_import_long_selected_identity_rejected_without_truncation(store, apply):
    with pytest.raises(tasks.WorkspaceIOError, match="80"):
        import_notes([{"title": "Foreign", "content": "Body", "project": LONG_B}], LONG_A, apply)
    assert store.list() == []


@pytest.mark.parametrize("apply", [False, True])
def test_import_compares_full_origin_identity_before_store_limit(store, apply):
    result = import_notes([{"title": "Foreign", "content": "Body", "project": LONG_B}], PREFIX, apply)
    assert result["counts"]["invalid"] == 1
    assert "diverge" in result["items"][0]["reason"]
    assert store.list() == []


@pytest.mark.parametrize("apply", [False, True])
def test_import_unselected_long_origin_fails_closed(store, apply):
    with pytest.raises(tasks.WorkspaceIOError, match="80"):
        import_notes([{"title": "Foreign", "content": "Body", "project": LONG_A}], apply=apply)
    assert store.list() == []


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("summary_note", [False, True])
def test_initialize_rejects_unsupported_identity_before_writes(store, tmp_path, apply, summary_note):
    project = SimpleNamespace(name=LONG_A, id="long", path=str(tmp_path))
    with pytest.raises(tasks.WorkspaceIOError, match="80"):
        tasks.run_initialize(project, Job("init", "initialize", project.id), apply=apply,
                             summary_note=summary_note, install_project_files=True)
    assert not tasks.index_path(project.id).exists()
    assert store.list() == []
    assert not (tmp_path / ".anamnesia").exists()


def test_memory_count_does_not_hide_unsupported_identity(store):
    with pytest.raises(tasks.WorkspaceIOError, match="80"):
        tasks.memory_count(LONG_A)


@pytest.mark.parametrize("name", [None, "", "   ", " alpha ", PREFIX])
def test_supported_identity_keeps_store_normalization(name):
    assert tasks._note_project(name) == ((name or "").strip() or None)


@pytest.mark.parametrize("apply", [False, True])
def test_existing_duplicate_is_scoped_to_destination_project(store, apply):
    store.save("Shared title", "Shared body", project="alpha")
    note = {"title": "Shared title", "content": "Shared body"}
    result = import_notes([note, note], "beta", apply)
    assert result["counts"]["duplicate"] == 1
    assert result["counts"]["imported"] == int(apply)
    assert result["counts"]["to_import"] == int(not apply)
    if apply:
        assert {n.project for n in store.list()} == {"alpha", "beta"}
        again = import_notes([note], "beta")
        assert again["counts"]["duplicate"] == 1
        assert again["counts"]["imported"] == 0


@pytest.mark.parametrize("apply", [False, True])
def test_batch_dedup_uses_each_destination_including_none(store, apply):
    notes = [{"title": "Shared", "content": "Body", "project": project}
             for project in ("alpha", "beta", None, "alpha", "beta", None)]
    result = import_notes(notes, apply=apply)
    assert result["counts"]["duplicate"] == 3
    assert result["counts"]["imported"] == (3 if apply else 0)
    assert result["counts"]["to_import"] == (0 if apply else 3)
    if apply:
        assert {n.project for n in store.list()} == {"alpha", "beta", None}
        again = import_notes(notes)
        assert again["counts"]["duplicate"] == 6
        assert again["counts"]["imported"] == 0


@pytest.mark.parametrize("apply", [False, True])
def test_unspecified_project_is_not_global_dedup_scope(store, apply):
    store.save("Shared", "Body", project="alpha")
    store.save("Unscoped", "Body", project=None)
    result = import_notes([{"title": "Shared", "content": "Body"},
                           {"title": "Unscoped", "content": "Body"}], apply=apply)
    assert result["counts"]["duplicate"] == 1
    assert result["counts"]["imported"] == int(apply)
    assert result["counts"]["to_import"] == int(not apply)
