"""TDD: scanner de workspace deve rejeitar junctions/reparse points do Windows
e qualquer entrada cujo realpath escape da raiz (não apenas symlinks)."""
from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.workspace_io import scanner


def _mk_junction(src: Path, dst: Path) -> None:
    """Cria uma junction NTFS real (não-admin) via _winapi."""
    if sys.platform != "win32":
        pytest.skip("real NTFS junction requires Windows")
    import _winapi

    _winapi.CreateJunction(str(src), str(dst))
    assert os.path.isjunction(dst)
    assert not dst.is_symlink()


def _rel_paths(res: scanner.ScanResult) -> set[str]:
    return {f.rel for f in res.files}


@pytest.fixture()
def arena(tmp_path: Path) -> tuple[Path, Path]:
    """(raiz do projeto, diretório externo com sentinela)."""
    outside = tmp_path / "fora"
    outside.mkdir()
    (outside / "sentinela.txt").write_text("LEAK", encoding="utf-8")
    root = tmp_path / "proj"
    root.mkdir()
    (root / "ok.txt").write_text("ok", encoding="utf-8")
    return root, outside


def test_junction_para_fora_nao_e_indexada(arena, monkeypatch):
    root, outside = arena
    junc = root / "junc"
    _mk_junction(outside, junc)
    _forbid_io(monkeypatch, outside, resolved=True)
    res = scanner.scan_project(root)
    rels = _rel_paths(res)
    assert "junc/sentinela.txt" not in rels
    assert "ok.txt" in rels
    # motivo registrado (junction rejeitada como link/escape)
    assert sum(res.skipped.values()) >= 1


def test_junction_aninhada_para_fora_nao_e_indexada(arena, monkeypatch):
    root, outside = arena
    sub = root / "sub"
    sub.mkdir()
    _mk_junction(outside, sub / "junc")
    _forbid_io(monkeypatch, outside, resolved=True)
    res = scanner.scan_project(root)
    rels = _rel_paths(res)
    assert "sub/junc/sentinela.txt" not in rels
    assert "ok.txt" in rels


def test_symlink_para_fora_nao_e_indexado(arena):
    root, outside = arena
    try:
        os.symlink(outside, root / "slink", target_is_directory=True)
    except OSError as exc:
        if sys.platform == "win32" and exc.winerror == 1314:
            pytest.skip("sem privilégio para criar symlink no Windows")
        raise
    res = scanner.scan_project(root)
    assert "slink/sentinela.txt" not in _rel_paths(res)
    assert "ok.txt" in _rel_paths(res)


def test_junction_para_dentro_tambem_e_rejeitada(arena):
    root, outside = arena
    dentro = root / "dentro"
    dentro.mkdir()
    (dentro / "alvo.txt").write_text("conteudo", encoding="utf-8")
    _mk_junction(dentro, root / "junc_in")
    res = scanner.scan_project(root)
    assert _rel_paths(res) == {"ok.txt", "dentro/alvo.txt"}
    assert res.skipped["link_simbolico"] == 1
    assert res.top_dirs == ["dentro"]


def test_raiz_junction_e_rejeitada_antes_de_ler(arena, monkeypatch):
    root, outside = arena
    link = root.parent / "aponta_fora"
    _mk_junction(outside, link)
    _forbid_io(monkeypatch, outside, resolved=True)
    res = scanner.scan_project(link)
    assert not res.files and not res.markers and not res.top_dirs
    assert res.skipped["link_simbolico"] == 1


@pytest.mark.skipif(sys.platform != "win32", reason="junctions são Windows-only")
def test_somente_windows_junction_eh_link(tmp_path):
    """Sanidade do helper: junction não é os.path.islink, mas é link para nós."""
    from app.workspace_io.scanner import _is_link

    alvo = tmp_path / "alvo"
    alvo.mkdir()
    _mk_junction(alvo, tmp_path / "j")
    assert not os.path.islink(str(tmp_path / "j"))
    assert _is_link(str(tmp_path / "j"))
    assert not _is_link(str(alvo))


def _forbid_io(monkeypatch, suspect: Path, *, resolved=False):
    """Guard reads AND traversal, including GitIgnore.load's Path.read_text."""
    original_open = builtins.open
    original_path_open = Path.open
    original_scandir = os.scandir
    original_resolve = Path.resolve
    target = original_resolve(suspect) if resolved else suspect

    def check(path):
        if not isinstance(path, int):
            p = original_resolve(Path(path)) if resolved else Path(path)
            assert not p.is_relative_to(target), f"forbidden synthetic I/O: {path}"

    def guarded_open(path, *args, **kwargs):
        check(path)
        return original_open(path, *args, **kwargs)

    def guarded_path_open(path, *args, **kwargs):
        check(path)
        return original_path_open(path, *args, **kwargs)

    def guarded_scandir(path):
        check(path)
        return original_scandir(path)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(os, "scandir", guarded_scandir)


def _mk_symlink(target, link):
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        if sys.platform == "win32" and exc.winerror == 1314:
            pytest.skip("Windows symlink privilege unavailable")
        raise


def test_symlink_root_is_rejected_before_io(arena, monkeypatch):
    root, outside = arena
    link = root.parent / "linked-root"
    _mk_symlink(outside, link)
    _forbid_io(monkeypatch, outside, resolved=True)
    result = scanner.scan_project(link)
    assert not result.files and not result.markers and not result.top_dirs
    assert result.skipped["link_simbolico"] == 1


@pytest.mark.parametrize("nested", [False, True])
def test_symlink_gitignore_is_not_loaded(arena, monkeypatch, nested):
    root, outside = arena
    parent = root / "sub" if nested else root
    parent.mkdir(exist_ok=True)
    (parent / "visible.txt").write_text("normal", encoding="utf-8")
    target = outside / "rules.txt"
    target.write_text("*.txt\n", encoding="utf-8")
    _mk_symlink(target, parent / ".gitignore")
    _forbid_io(monkeypatch, outside, resolved=True)
    result = scanner.scan_project(root)
    visible = "sub/visible.txt" if nested else "visible.txt"
    assert visible in _rel_paths(result) and "ok.txt" in _rel_paths(result)
    assert not any(f.rel.endswith(".gitignore") for f in result.files)
    assert ".gitignore" not in result.markers
    assert result.skipped["link_simbolico"] == 1


@pytest.mark.parametrize("kind", ["file", "directory", "gitignore", "nested_gitignore"])
def test_resolved_escape_is_rejected_even_without_link_flag(arena, monkeypatch, kind):
    root, outside = arena
    parent = root
    if kind == "nested_gitignore":
        parent = root / "sub"
        parent.mkdir()
    suspect = parent / (".gitignore" if "gitignore" in kind else "escape")
    if kind == "directory":
        suspect.mkdir()
        (suspect / "visible.txt").write_text("normal", encoding="utf-8")
        target = outside
    else:
        suspect.write_text("*.txt\n" if "gitignore" in kind else "normal", encoding="utf-8")
        target = outside / "sentinela.txt"
    original_resolve = Path.resolve

    def redirected_resolve(path, *args, **kwargs):
        if path == suspect:
            return target
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected_resolve)
    _forbid_io(monkeypatch, suspect)
    result = scanner.scan_project(root)
    assert _rel_paths(result) == {"ok.txt"}
    assert result.skipped["fora_da_raiz"] >= 1
    assert ".gitignore" not in result.markers


@pytest.mark.parametrize("root_reparse", [False, True])
def test_generic_reparse_attribute_is_rejected(arena, monkeypatch, root_reparse):
    root, _ = arena
    suspect = root if root_reparse else root / "ok.txt"
    original_lstat = os.lstat

    def reparse_lstat(path, *args, **kwargs):
        st = original_lstat(path, *args, **kwargs)
        if Path(path) == suspect:
            return SimpleNamespace(st_mode=st.st_mode, st_file_attributes=0x400)
        return st

    monkeypatch.setattr(os, "lstat", reparse_lstat)
    result = scanner.scan_project(root)
    assert not result.files
    assert result.skipped["link_simbolico"] == 1


def test_normal_nested_project_retains_gitignore_and_metadata(arena):
    root, _ = arena
    (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
    sub = root / "src"
    sub.mkdir()
    (sub / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (sub / "main.py").write_text("print('normal')\n", encoding="utf-8")
    (sub / "ignored.txt").write_text("ignored", encoding="utf-8")
    (root / "debug.log").write_text("ignored", encoding="utf-8")
    result = scanner.scan_project(root)
    assert _rel_paths(result) == {"ok.txt", ".gitignore", "src/.gitignore", "src/main.py"}
    assert result.top_dirs == ["src"]
    assert result.markers == [".gitignore"]
    assert result.languages["Python"] == 1
    assert result.skipped["gitignore"] == 2
