from pathlib import Path

import pytest

import app.services.obsidian as obsidian
from app.services.obsidian import ObsidianVault, VaultAccessError, split_sections


def test_module_has_no_mutating_functions():
    for name in ("write", "delete", "rename", "move"):
        assert not hasattr(obsidian, name)
        assert not hasattr(ObsidianVault, name)


def test_list_markdown_skips_obsidian(tiny_vault):
    v = ObsidianVault(tiny_vault)
    files = v.list_markdown()
    assert len(files) == 4
    assert not any(".obsidian" in f for f in files)
    assert "20-Dev-IA/decisao-stack.md" in files
    assert files == sorted(files)


def test_read_works(tiny_vault):
    v = ObsidianVault(tiny_vault)
    assert "FastAPI" in v.read("20-Dev-IA/decisao-stack.md")


def test_path_traversal_rejected(tiny_vault):
    v = ObsidianVault(tiny_vault)
    (tiny_vault.parent / "x.md").write_text("fora", encoding="utf-8")
    with pytest.raises(VaultAccessError):
        v.read("../x.md")


def test_absolute_path_outside_rejected(tiny_vault, tmp_path):
    v = ObsidianVault(tiny_vault)
    outside = tmp_path / "outside.md"
    outside.write_text("fora", encoding="utf-8")
    with pytest.raises(VaultAccessError):
        v.read(str(outside))


def test_guard_write_raises(tiny_vault):
    v = ObsidianVault(tiny_vault)
    for op in ("write", "delete", "rename", "move"):
        with pytest.raises(VaultAccessError):
            v._guard(op)


def test_vault_access_error_is_permission_error():
    assert issubclass(VaultAccessError, PermissionError)


def test_state_hash_unchanged_after_reads(tiny_vault):
    v = ObsidianVault(tiny_vault)
    before = v.state_hash()
    for rel in v.list_markdown():
        v.read(rel)
    after = v.state_hash()
    assert before == after
    assert ObsidianVault.digest(before) == ObsidianVault.digest(after)
    assert len(before) == 4


def test_split_sections_ignores_headings_in_code_fence(tiny_vault):
    text = Path(tiny_vault / "20-Dev-IA/snippet-codigo.md").read_text(encoding="utf-8")
    secs = split_sections(text)
    paths = [s.heading_path for s in secs]
    assert paths == ["Snippet de Configuração", "Snippet de Configuração > Observações"]
    assert not any("not a heading" in p for p in paths)
    assert "# not a heading" in secs[0].text


def test_split_sections_builds_heading_paths():
    text = "# A\nintro\n## B\ncorpo b\n### C\ncorpo c\n## D\ncorpo d\n# E\ncorpo e\n"
    paths = [s.heading_path for s in split_sections(text)]
    assert paths == ["A", "A > B", "A > B > C", "A > D", "E"]
