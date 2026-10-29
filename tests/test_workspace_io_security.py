"""Workspace IO security regressions: synthetic notes only, no private vault."""
import json
from types import SimpleNamespace

import pytest

from app.memory_store.store import SavedContextStore, SavedNote
from app.workspace_io import tasks
from app.workspace_io.jobs import JobManager


def export(kind="memories", fmt="json", **kwargs):
    job = JobManager().submit("export", None, "synthetic", lambda j: tasks.run_export(
        kind, fmt, j, apply=True, **kwargs), synchronous=True)
    if job.exc:
        raise job.exc
    assert job.artifact is not None
    assert job.result is not None
    return job, job.artifact["data"].decode("utf-8-sig")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "home"))
    s = SavedContextStore(tmp_path / "notes", rate_per_min=0)
    monkeypatch.setattr(tasks, "import_store", lambda: s)
    return s


# Construct a recognizable synthetic token at runtime, never a credential.
SECRET = "sk-" + "syntheticfixture" * 2


@pytest.mark.parametrize("fmt", ["json", "md", "csv"])
@pytest.mark.parametrize("kind", ["memories", "context", "metadata"])
@pytest.mark.parametrize("field", ["id", "title", "project", "tags", "kind", "status", "created", "updated", "source", "source_agent", "content"])
def test_export_redacts_each_text_field(store, monkeypatch, fmt, kind, field):
    note = SavedNote(id="0123456789", title="Synthetic title", content="Synthetic body", project="alpha", status="active")
    setattr(note, field, [SECRET] if field == "tags" else SECRET)
    monkeypatch.setattr(store, "list", lambda **kw: [note])  # legacy/corrupt metadata fixture
    job, body = export(kind, fmt, scope="all")
    assert SECRET not in body
    assert SECRET not in json.dumps(job.result)
    # Context omits non-active notes before serializing them.
    assert job.result["redacted_records"] == (0 if kind == "context" and field == "status" else 1)


def test_export_redacts_scope_and_filename(store):
    store.save("Synthetic", "Body", project="alpha")
    job, body = export(scope="project", project=SimpleNamespace(name=SECRET, id="alpha"))
    assert SECRET not in body
    assert SECRET not in json.dumps(job.result)
    assert "syntheticfixture" not in job.artifact["filename"]


@pytest.mark.parametrize("fmt", ["json", "md", "csv"])
def test_report_scope_filters_before_audit_and_usefulness(store, fmt):
    alpha = store.save("Alpha title", "Unique alpha content", project="alpha")
    beta = store.save("Beta PRIVATE title", "Unique alpha content", project="beta")
    store._mutate(alpha, feedback_useful=2)
    store._mutate(beta, feedback_wrong=9, feedback_stale=8)
    project = SimpleNamespace(name="alpha", id="alpha-id")
    _, before = export("report", fmt, scope="project", project=project)
    assert beta not in before and "Beta PRIVATE" not in before
    if fmt == "json":
        report = json.loads(before)["data"]
        assert report["audit"]["total"] == 1
        assert report["audit"]["wrong_flagged"] == 0
        assert report["audit"]["stale_flagged"] == 0
        assert report["audit"]["duplicates"] == 0
        assert report["audit"]["duplicate_rate"] == 0
        assert [r["id"] for r in report["usefulness_top"]] == [alpha]
        assert report["audit"]["trash"] is None  # trash cannot safely be attributed to a project
    # Foreign mutations must not change even aggregate counters (or trash counts).
    store.delete(beta)
    store.save("Another private beta", "Unrelated beta second", project="beta")
    _, after = export("report", fmt, scope="project", project=project)
    # generated_at is metadata; freeze only that nondeterministic field for comparison.
    if fmt == "json":
        assert json.loads(before)["data"] == json.loads(after)["data"]
    else:
        import re
        assert re.sub(r"generated_at:.*", "", before) == re.sub(r"generated_at:.*", "", after)


@pytest.mark.parametrize("fmt", ["json", "md", "csv"])
def test_report_redacts_nested_fields(store, monkeypatch, fmt):
    note = SavedNote(id=SECRET, title=SECRET, content="body", project="alpha", kind=SECRET,
                     feedback_useful=1)
    monkeypatch.setattr(store, "list", lambda **kw: [note])
    _, body = export("report", fmt, scope="all")
    assert SECRET not in body


@pytest.mark.parametrize("fmt", ["json", "md", "csv"])
@pytest.mark.parametrize("kind", ["index", "metrics"])
def test_other_export_kinds_redact_text(store, monkeypatch, fmt, kind):
    monkeypatch.setattr(tasks, "load_index", lambda _: {"files": {SECRET: {"size": 1, "sha256": SECRET, "ext": SECRET}}})
    monkeypatch.setattr(tasks, "_metrics", lambda _: ({SECRET: SECRET}, [{"project": SECRET, "agent": SECRET}]))
    _, body = export(kind, fmt, scope="project", project=SimpleNamespace(name=SECRET, id="alpha"))
    assert SECRET not in body


@pytest.mark.parametrize("kind", tasks.EXPORT_KINDS)
@pytest.mark.parametrize("scope", ["project", "bogus", None])
def test_export_fails_closed_without_project(store, kind, scope):
    with pytest.raises(tasks.WorkspaceIOError) as error:
        export(kind, scope=scope)
    assert error.value.code == ("project_required" if scope == "project" else "invalid_scope")


def test_only_explicit_all_exports_without_project(store):
    store.save("Alpha", "body alpha", project="alpha")
    store.save("Beta", "body beta", project="beta")
    with pytest.raises(tasks.WorkspaceIOError, match="projeto"):
        export()
    _, body = export(scope="all")
    assert len(json.loads(body)["data"]) == 2


@pytest.fixture
def client(store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import workspace_io as api
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.require_local_write] = lambda: None
    app.dependency_overrides[api.get_registry] = lambda: SimpleNamespace(get=lambda _: None)
    app.dependency_overrides[api.get_jobs] = lambda: JobManager()
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("kind", tasks.EXPORT_KINDS)
@pytest.mark.parametrize("apply", [False, True])
def test_api_requires_project_before_creating_job(client, kind, apply):
    response = client.post("/api/workspace/io/export", json={"kind": kind, "dry_run": not apply})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "project_required"


def test_ui_blocks_missing_project_before_post():
    import shutil
    import subprocess
    from pathlib import Path
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    source = (Path(__file__).parents[1] / "frontend/js/pages/workspace.js").read_text(encoding="utf-8")
    html = source[source.index("function wioExportHtml("):source.index("function wioHistoryHtml(")]
    submit = source[source.index("async function wioSubmit("):source.index("function wioStartPolling(")]
    harness = r'''
const assert = require('node:assert/strict');
const wio = {busy:false, status:{data:null, apiMissing:false}, exportOpts:{kind:'memories',format:'json',scope:'project'},errs:{},jobs:{}};
const esc = String, wioProject = () => null, wioJobPanel = () => '';
const I18N = {workspace:{}}, activeProjectId = null, WIO_PATH = {export:'export'};
let posts=0; const toast=()=>{}, refresh=()=>{}, wioStopPolling=()=>{}, wioLoadStatus=()=>{}, call=async()=>{ posts++; return {job:{state:'done'}}; };
'''
    harness += html + submit + r'''
(async()=>{
  assert.match(wioExportHtml({}), /data-kind="export" disabled/);
  await wioSubmit({isConnected:true},'export',true);
  assert.equal(posts,0, 'missing project must not POST');
  wio.exportOpts.scope='all';
  assert.doesNotMatch(wioExportHtml({}), /data-kind="export" disabled/);
  await wioSubmit({isConnected:true},'export',true);
  assert.equal(posts,1, 'explicit all remains allowed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run([node, "-"], input=harness, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def run_import(store, notes, *, apply, project_name=None, extension="json"):
    text = json.dumps(notes) if extension == "json" else notes
    job = JobManager().submit("import", None, "synthetic", lambda j: tasks.run_import(
        [("synthetic." + extension, text)], j, apply=apply, project_name=project_name), synchronous=True)
    if job.exc:
        raise job.exc
    return job.result


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("field,value", [("project", 123), ("project", True), ("project", []),
    ("title", 12), ("content", {}), ("tags", {"tag": "x"}), ("tags", [123]),
    ("kind", []), ("source", {}), ("source_agent", ["agent"])])
def test_json_types_are_controlled_per_item(store, apply, field, value):
    note = {"title": "Invalid synthetic", "content": "Bad body", field: value}
    result = run_import(store, [note, {"title": "Good synthetic", "content": "Good body"}], apply=apply)
    assert result["counts"]["invalid"] == 1
    assert result["counts"]["to_import"] == int(not apply)
    assert result["counts"]["imported"] == int(apply)
    assert field in result["items"][0]["reason"]
    assert len(store.list()) == int(apply)


@pytest.mark.parametrize("extension", ["json", "md"])
@pytest.mark.parametrize("apply", [False, True])
def test_import_rejects_explicit_cross_project_destination(store, apply, extension):
    note = [{"title": "Foreign synthetic", "content": "Foreign body", "project": "beta"}]
    if extension == "md":
        note = "---\ntitle: Foreign synthetic\nproject: beta\n---\nForeign body"
    result = run_import(store, note, apply=apply, project_name="alpha", extension=extension)
    assert result["counts"]["invalid"] == 1 and result["counts"]["to_import"] == 0 and result["counts"]["imported"] == 0
    assert "projeto" in result["items"][0]["reason"].lower()
    assert store.list() == []


@pytest.mark.parametrize("project", [None, "alpha"])
def test_import_matching_or_unspecified_project_still_works(store, project):
    result = run_import(store, [{"title": "Good", "content": "Body", "project": project}],
                        apply=True, project_name="alpha")
    assert result["counts"]["imported"] == 1
    assert store.list()[0].project == "alpha"


def test_api_invalid_json_metadata_returns_controlled_result(client):
    response = client.post("/api/workspace/io/import", json={"source": "upload", "dry_run": True,
        "files": [{"name": "synthetic.json", "content": json.dumps([{"title": "Synthetic", "content": "Body", "project": 123}])}]})
    assert response.status_code == 200
    assert response.json()["job"]["result"]["counts"]["invalid"] == 1
