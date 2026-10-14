"""T10.8: read-only explorer, content search confined to the project (.., symlinks, junctions)."""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.terminals.projects import PathEscapeError, list_dir, safe_join, search_content, search_names


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "a.txt").write_text("alpha\nbeta NEEDLE gamma\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "n.js").write_text("needle", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("needle", encoding="utf-8")
    (root / "img.bin").write_bytes(b"\x89PNG\x00needle\x00")
    (root / "huge.txt").write_text("needle " * 5000, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle outside", encoding="utf-8")
    return root, outside


def _link_dir(link, target):
    if sys.platform == "win32":  # junction: no admin needed
        cp = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if cp.returncode != 0:
            pytest.skip("cannot create junction")
    else:
        os.symlink(target, link, target_is_directory=True)


def test_finds_text_skips_binary_git_node_modules_and_big(proj):
    root, _ = proj
    r = search_content(str(root), "needle", max_file_bytes=10_000)
    assert [(h["path"], h["line"]) for h in r["results"]] == [("sub/a.txt", 2)]
    assert "NEEDLE" in r["results"][0]["snippet"]


def test_result_cap_and_timeout_flag_truncated(proj):
    root, _ = proj
    assert search_content(str(root), "needle", cap=1)["truncated"] is True
    t = iter(range(0, 100000, 100))
    r = search_content(str(root), "needle", max_seconds=50, clock=lambda: next(t))
    assert r["truncated"] is True


def test_dotdot_and_absolute_paths_rejected(proj):
    root, outside = proj
    for rel in ("..", "../outside", "sub/../..", str(outside)):
        with pytest.raises(PathEscapeError):
            safe_join(str(root), rel)
        with pytest.raises(PathEscapeError):
            search_content(str(root), "needle", rel)
        with pytest.raises(PathEscapeError):
            list_dir(str(root), rel)


def test_symlink_or_junction_dir_not_followed_or_entered(proj):
    root, outside = proj
    _link_dir(root / "lnk", outside)
    r = search_content(str(root), "needle", max_file_bytes=10_000)
    assert all("outside" not in h["snippet"] and not h["path"].startswith("lnk") for h in r["results"])
    assert all(not h["path"].startswith("lnk/") for h in search_names(str(root), "secret")["results"])
    with pytest.raises(PathEscapeError):
        search_content(str(root), "needle", "lnk")
    with pytest.raises(PathEscapeError):
        list_dir(str(root), "lnk")


def test_symlink_file_not_read(proj):
    root, outside = proj
    try:
        os.symlink(outside / "secret.txt", root / "flink.txt")
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege")
    assert search_content(str(root), "outside")["results"] == []
