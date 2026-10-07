"""Project registry, path safety (S5), launch profiles."""
from __future__ import annotations

import os
import sys

import pytest

from app.terminals.profiles import Profile, ProfileUnavailable, load_profiles
from app.terminals.projects import (PathEscapeError, ProjectError, ProjectRegistry, list_dir,
                                    safe_join, search_names)


@pytest.fixture
def reg(tmp_path):
    return ProjectRegistry(tmp_path / "data" / "anamnesia.db")


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    (root / "README.md").write_text("hi")
    (root / "sub" / "Notes.txt").write_text("x")
    (root / ".git").mkdir()
    (root / ".git" / "readme-hidden").write_text("x")
    return root


def test_add_list_get_remove_keeps_files(reg, tree):
    p = reg.add("Meu", str(tree))
    assert p.path == str(tree.resolve())
    assert [x.id for x in reg.list()] == [p.id]
    assert reg.get(p.id) == p
    assert reg.remove(p.id) is True and reg.remove(p.id) is False
    assert reg.list() == [] and (tree / "README.md").exists()


def test_registry_persists_across_instances(tmp_path, tree):
    db = tmp_path / "a.db"
    p = ProjectRegistry(db).add("x", str(tree))
    assert ProjectRegistry(db).get(p.id).name == "x"


def test_add_rejects_bad_input(reg, tree, tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    with pytest.raises(ProjectError):
        reg.add("f", str(f))
    with pytest.raises(ProjectError):
        reg.add("n", str(tmp_path / "missing"))
    with pytest.raises(ProjectError):
        reg.add("  ", str(tree))
    reg.add("ok", str(tree))
    with pytest.raises(ProjectError):
        reg.add("dup", str(tree))


def test_default_registry_uses_user_data_dir(tmp_path, monkeypatch):
    from config import paths

    monkeypatch.setenv(paths.HOME_ENV_VAR, str(tmp_path / "home"))
    r = ProjectRegistry()
    assert r.db_path == (tmp_path / "home").resolve() / "anamnesia.db"


def test_safe_join_ok_and_dotdot(tree):
    assert safe_join(tree, "") == tree.resolve()
    assert safe_join(tree, "sub/Notes.txt") == (tree / "sub" / "Notes.txt").resolve()
    assert safe_join(tree, "not/yet/there") == (tree / "not" / "yet" / "there").resolve()
    for bad in ("..", "../x", "sub/../../x", "sub\\..\\..\\x", "a/..", "x\x00y"):
        with pytest.raises(PathEscapeError):
            safe_join(tree, bad)


def test_safe_join_rejects_absolute(tree, tmp_path):
    with pytest.raises(PathEscapeError):
        safe_join(tree, str(tmp_path))
    with pytest.raises(PathEscapeError):
        safe_join(tree, "/etc/passwd")
    if os.name == "nt":
        with pytest.raises(PathEscapeError):
            safe_join(tree, "C:\\Windows")
        with pytest.raises(PathEscapeError):
            safe_join(tree, "file.txt:stream")


def _symlink(link, target, is_dir=True):
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks cannot be created here")


def test_safe_join_blocks_symlink_escape(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    _symlink(tree / "link", outside)
    with pytest.raises(PathEscapeError):
        safe_join(tree, "link")
    with pytest.raises(PathEscapeError):
        safe_join(tree, "link/secret.txt")


def test_symlink_inside_project_is_allowed(tree):
    _symlink(tree / "alias", tree / "sub")
    assert safe_join(tree, "alias/Notes.txt") == (tree / "sub" / "Notes.txt").resolve()


def test_list_dir_hides_escaping_symlinks_and_caps(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(tree / "link", outside)
    out = list_dir(str(tree), "")
    names = [e["name"] for e in out["entries"]]
    assert "link" not in names and "sub" in names and "README.md" in names
    assert names.index("sub") < names.index("README.md")  # dirs first
    capped = list_dir(str(tree), "", cap=1)
    assert len(capped["entries"]) == 1 and capped["truncated"] is True
    assert [e["name"] for e in list_dir(str(tree), "sub")["entries"]] == ["Notes.txt"]
    with pytest.raises(PathEscapeError):
        list_dir(str(tree), "..")
    with pytest.raises(ProjectError):
        list_dir(str(tree), "README.md")


def test_search_names(tree):
    out = search_names(str(tree), "NOTES")
    assert [r["path"] for r in out["results"]] == ["sub/Notes.txt"]
    assert search_names(str(tree), "readme")["results"][0]["path"] == "README.md"  # .git skipped
    assert len(search_names(str(tree), "e", cap=1)["results"]) == 1
    with pytest.raises(PathEscapeError):
        search_names(str(tree), "x", "../")


# ------------------------------------------------------------------ profiles
def test_default_profiles_yaml():
    p = load_profiles()
    assert {"shell", "powershell", "hermes", "claude-code", "codex", "opencode"} <= set(p)
    assert p["claude-code"].command == "claude" and p["claude-code"].env_keys == ("ANTHROPIC_API_KEY",)
    assert p["shell"].windows_command == "cmd.exe"
    assert p["hermes"].env_keys == ()


def test_shell_profile_resolves_here():
    d = load_profiles()["shell"].describe()
    assert d["available"] is True  # cmd.exe on Windows, bash/sh elsewhere


def test_describe_never_leaks_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-very-secret")
    d = load_profiles()["claude-code"].describe()
    assert "sk-very-secret" not in repr(d) and d["missing_env_keys"] == []
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert load_profiles()["claude-code"].describe()["missing_env_keys"] == ["ANTHROPIC_API_KEY"]


def test_unavailable_profile_and_argv():
    p = Profile(id="x", name="x", command="no-such-cmd-xyz")
    assert p.describe()["available"] is False
    with pytest.raises(ProfileUnavailable):
        p.argv()
    q = Profile(id="y", name="y", command=sys.executable, args=("-V",))
    assert q.argv()[1:] == ["-V"]


def test_invalid_profiles_file(tmp_path):
    from app.terminals.profiles import ProfileError

    f = tmp_path / "p.yaml"
    f.write_text("version: 1\nprofiles:\n  - id: a\n", encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profiles(f)
