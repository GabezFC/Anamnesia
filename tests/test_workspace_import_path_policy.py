"""Synthetic path-import policy regressions; never access a real vault."""
from pathlib import Path
import builtins
import os
import sys

import pytest

from app.workspace_io import scanner, tasks
from app.workspace_io.jobs import Cancelled, Job


JOB = Job("synthetic-import", "import", None)


@pytest.mark.parametrize("selection", ["private/note.md", "private", "credentials.json", "."])
def test_original_root_policy_blocks_ignored_and_named_secret(tmp_path, monkeypatch, selection):
    (tmp_path / ".gitignore").write_text("private/\n", encoding="utf-8")
    (tmp_path / "private").mkdir()
    (tmp_path / "private/note.md").write_text("Synthetic private note", encoding="utf-8")
    (tmp_path / "credentials.json").write_text('{"content":"Synthetic credential fixture"}', encoding="utf-8")
    forbid_content_reads(monkeypatch, [tmp_path / "private/note.md", tmp_path / "credentials.json"])
    assert tasks.gather_import_path(tmp_path, selection, JOB) == []


def forbid_content_reads(monkeypatch, paths):
    """Catch both scanner head probes and import content reads."""
    paths = {Path(p).resolve() for p in paths}
    original_open, original_path_open = builtins.open, Path.open

    def check(path):
        if not isinstance(path, int):
            assert Path(path).resolve() not in paths, f"forbidden read: {path}"

    def guarded_open(path, *args, **kwargs):
        check(path)
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        check(path)
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)


@pytest.mark.parametrize("selection", ["docs", "docs/ok.MD", "./docs/ok.MD", "docs\\ok.MD"])
def test_selection_reads_only_selected_eligible_content(tmp_path, monkeypatch, selection):
    (tmp_path / ".gitignore").write_text("docs/ignored.md\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    allowed = tmp_path / "docs/ok.MD"
    allowed.write_text("# Synthetic selected note", encoding="utf-8")
    blocked = [tmp_path / name for name in (
        "other.md", "arbitrary.odd", "docs/ignored.md", "docs/credentials.json", "docs/source.py")]
    for p in blocked:
        p.write_text("Synthetic unselected data", encoding="utf-8")
    forbid_content_reads(monkeypatch, blocked)
    assert tasks.gather_import_path(tmp_path, selection, JOB) == [("docs/ok.MD", "# Synthetic selected note")]


def test_whole_root_does_not_probe_unselected_formats(tmp_path, monkeypatch):
    (tmp_path / "note.md").write_text("Synthetic note", encoding="utf-8")
    blocked = [tmp_path / name for name in ("legitimate.unusual", "module.py", "data.csv")]
    for p in blocked:
        p.write_text("Synthetic legitimate project data", encoding="utf-8")
    forbid_content_reads(monkeypatch, blocked)
    assert tasks.gather_import_path(tmp_path, ".", JOB) == [("note.md", "Synthetic note")]


@pytest.mark.parametrize("selection", ["docs", "docs/child", "docs/child/hidden.md"])
def test_nested_ignores_and_prefix_boundaries(tmp_path, selection):
    (tmp_path / "docs/child").mkdir(parents=True)
    (tmp_path / "docs-other").mkdir()
    (tmp_path / "docs/.gitignore").write_text("child/hidden.md\n", encoding="utf-8")
    (tmp_path / "docs/child/hidden.md").write_text("Synthetic ignored", encoding="utf-8")
    (tmp_path / "docs-other/foreign.md").write_text("Synthetic sibling", encoding="utf-8")
    assert tasks.gather_import_path(tmp_path, selection, JOB) == []


@pytest.mark.parametrize("directory", [False, True])
def test_scanner_default_size_policy_is_not_relaxed_for_imports(tmp_path, directory):
    (tmp_path / "notes").mkdir()
    p = tmp_path / "notes/note.md"
    p.write_bytes(b"x" * (scanner.DEFAULT_MAX_FILE_BYTES + 1))
    selection = "notes" if directory else "notes/note.md"
    assert tasks.gather_import_path(tmp_path, selection, JOB) == []


@pytest.mark.parametrize("kind", ["empty", "binary", "large", "dependency"])
@pytest.mark.parametrize("directory", [False, True])
def test_file_and_directory_share_eligibility(tmp_path, kind, directory):
    parent = tmp_path / ("node_modules" if kind == "dependency" else "notes")
    parent.mkdir()
    p = parent / "note.md"
    data = {"empty": b"", "binary": b"a\x00b", "large": b"x" * (tasks.MAX_IMPORT_FILE_BYTES + 1),
            "dependency": b"Synthetic dependency"}[kind]
    p.write_bytes(data)
    selected = parent if directory else p
    assert tasks.gather_import_path(tmp_path, selected.relative_to(tmp_path).as_posix(), JOB) == []


@pytest.mark.parametrize("selection", ["../outside.md", "/absolute.md", "nested/../../outside.md"])
def test_containment_is_preserved(tmp_path, selection):
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(tmp_path, selection, JOB)
    assert error.value.code == "path_escape"


def test_missing_path_and_cancel_are_controlled(tmp_path):
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(tmp_path, "missing.md", JOB)
    assert error.value.code == "not_found"
    (tmp_path / "ok.md").write_text("Synthetic", encoding="utf-8")
    with pytest.raises(Cancelled):
        tasks.gather_import_path(tmp_path, ".", Job("cancelled", "import", None, cancel_requested=True))


@pytest.mark.parametrize("selection", ["notes", "notes/note.md"])
def test_scan_budget_is_root_wide_even_for_file_selection(tmp_path, monkeypatch, selection):
    monkeypatch.setattr(tasks, "MAX_IMPORT_ITEMS", 1)
    for i in range(21):
        (tmp_path / f"a{i:02}.odd").write_text("Synthetic unselected", encoding="utf-8")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes/note.md").write_text("Synthetic note", encoding="utf-8")
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(tmp_path, selection, JOB)
    assert error.value.code == "scan_limit"


def test_item_and_total_byte_limits(tmp_path, monkeypatch):
    for name in ("a.md", "b.md"):
        (tmp_path / name).write_text("Synthetic note", encoding="utf-8")
    monkeypatch.setattr(tasks, "MAX_IMPORT_ITEMS", 1)
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(tmp_path, ".", JOB)
    assert error.value.code == "too_many_items"
    monkeypatch.setattr(tasks, "MAX_IMPORT_ITEMS", 500)
    monkeypatch.setattr(tasks, "MAX_IMPORT_BYTES", 2)
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(tmp_path, ".", JOB)
    assert error.value.code == "too_large"


def junction(target, link):
    if sys.platform != "win32":
        pytest.skip("NTFS junction requires Windows")
    import _winapi
    _winapi.CreateJunction(str(target), str(link))
    assert os.path.isjunction(link)


@pytest.mark.parametrize("selection", ["alias", "alias/note.md"])
def test_in_root_junction_alias_is_not_resolved_into_eligible_path(tmp_path, selection):
    (tmp_path / "actual").mkdir()
    (tmp_path / "actual/note.md").write_text("Synthetic target", encoding="utf-8")
    junction(tmp_path / "actual", tmp_path / "alias")
    assert tasks.gather_import_path(tmp_path, selection, JOB) == []


@pytest.mark.parametrize("selection", ["alias", "alias/note.md"])
def test_external_junction_is_never_read(tmp_path, monkeypatch, selection):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "note.md").write_text("Synthetic outside", encoding="utf-8")
    junction(outside, root / "alias")
    forbid_content_reads(monkeypatch, [outside / "note.md"])
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(root, selection, JOB)
    assert error.value.code == "path_escape"


def test_junction_root_is_rejected_without_content_reads(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "note.md").write_text("Synthetic note", encoding="utf-8")
    junction(actual, tmp_path / "root")
    forbid_content_reads(monkeypatch, [actual / "note.md"])
    assert tasks.gather_import_path(tmp_path / "root", ".", JOB) == []


def test_reparse_swap_after_scan_is_rechecked(tmp_path, monkeypatch):
    root, outside = tmp_path / "root", tmp_path / "outside"
    (root / "notes").mkdir(parents=True)
    outside.mkdir()
    (root / "notes/note.md").write_text("Synthetic before", encoding="utf-8")
    (outside / "note.md").write_text("Synthetic outside", encoding="utf-8")
    original_scan = tasks.scan_project

    def swapped_scan(*args, **kwargs):
        scan = original_scan(*args, **kwargs)
        (root / "notes/note.md").unlink()
        (root / "notes").rmdir()
        junction(outside, root / "notes")
        return scan

    monkeypatch.setattr(tasks, "scan_project", swapped_scan)
    forbid_content_reads(monkeypatch, [outside / "note.md"])
    assert tasks.gather_import_path(root, "notes", JOB) == []


def test_content_growth_after_scan_has_a_bounded_read(tmp_path, monkeypatch):
    p = tmp_path / "note.md"
    p.write_text("Before", encoding="utf-8")
    original_scan = tasks.scan_project

    def growing_scan(*args, **kwargs):
        scan = original_scan(*args, **kwargs)
        p.write_bytes(b"x" * (scanner.DEFAULT_MAX_FILE_BYTES + 1))
        return scan

    monkeypatch.setattr(tasks, "scan_project", growing_scan)
    assert tasks.gather_import_path(tmp_path, "note.md", JOB) == []


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows case-insensitive path semantics")
@pytest.mark.parametrize("selection", ["docs/note.md", "docs", "DOCS/NOTE.MD", "dOcS"])
def test_windows_selection_matches_existing_path_case_insensitively(tmp_path, monkeypatch, selection):
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs/Note.md").write_text("Synthetic selected note", encoding="utf-8")
    (tmp_path / "Docs-other").mkdir()
    sibling = tmp_path / "Docs-other/Foreign.md"
    sibling.write_text("Synthetic unselected sibling", encoding="utf-8")
    assert (tmp_path / "docs/note.md").is_file()
    forbid_content_reads(monkeypatch, [sibling])
    assert tasks.gather_import_path(tmp_path, selection, JOB) == [("Docs/Note.md", "Synthetic selected note")]


@pytest.mark.skipif(sys.platform == "win32", reason="native POSIX case-sensitive path semantics")
def test_posix_selection_does_not_fold_case(tmp_path):
    (tmp_path / "Docs").mkdir()
    (tmp_path / "Docs/Note.md").write_text("Synthetic note", encoding="utf-8")
    with pytest.raises(tasks.WorkspaceIOError) as error:
        tasks.gather_import_path(tmp_path, "docs/note.md", JOB)
    assert error.value.code == "not_found"
