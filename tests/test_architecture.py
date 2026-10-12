"""ANA-081: architecture gate (layer contract + import cycles) as a test, plus mutation tests of the checker."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_architecture.py"

_spec = importlib.util.spec_from_file_location("check_architecture", SCRIPT)
ca = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["check_architecture"] = ca
_spec.loader.exec_module(ca)  # type: ignore[union-attr]


def _make(tmp_path: Path, files: dict[str, str], layers_toml: str) -> tuple[Path, Path]:
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(src), encoding="utf-8")
    cfg = tmp_path / "layers.toml"
    cfg.write_text(textwrap.dedent(layers_toml), encoding="utf-8")
    return tmp_path, cfg


LAYERS = """
roots = ["app"]
[layers]
"app.low" = 0
"app.high" = 1
"""


def test_repo_architecture_is_clean():
    res = ca.check(ROOT, ca.DEFAULT_LAYERS)
    assert res["violations"] == [], res["violations"]
    assert res["cycles"] == [], res["cycles"]
    assert res["modules"] > 100  # sanity: the walker really saw the code base


def test_repo_contract_covers_every_app_subpackage():
    res = ca.check(ROOT, ca.DEFAULT_LAYERS)
    assert res["unmapped"] == [], f"add these packages to scripts/layers.toml: {res['unmapped']}"


def test_repo_contract_stale_allowances_are_only_reported():
    """A fixed upward import leaves a stale `allowed_upward` entry; the CLI prints a note (cleanup, not a failure)."""
    res = ca.check(ROOT, ca.DEFAULT_LAYERS)
    assert isinstance(res["stale_allowed"], list)


def test_cli_exit_code_zero_on_repo():
    r = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip().endswith("OK")


def test_toplevel_upward_import_is_a_violation(tmp_path):
    root, cfg = _make(tmp_path, {
        "app/__init__.py": "", "app/low/__init__.py": "", "app/high/__init__.py": "",
        "app/low/a.py": "from app.high import b\n",
        "app/high/b.py": "X = 1\n",
    }, LAYERS)
    res = ca.check(root, cfg)
    assert [(v["importer"], v["imported"], v["kind"]) for v in res["violations"]] == [
        ("app.low.a", "app.high.b", "top-level")]


def test_lazy_upward_import_needs_a_whitelist_entry(tmp_path):
    files = {"app/__init__.py": "", "app/low/__init__.py": "", "app/high/__init__.py": "",
             "app/low/a.py": "def f():\n    from app.high import b\n    return b\n", "app/high/b.py": "X = 1\n"}
    root, cfg = _make(tmp_path, files, LAYERS)
    assert [v["kind"] for v in ca.check(root, cfg)["violations"]] == ["lazy"]
    root, cfg = _make(tmp_path, {}, LAYERS + '\n[[allowed_upward]]\nedge = ["app.low", "app.high"]\n')
    res = ca.check(root, cfg)
    assert res["violations"] == [] and res["stale_allowed"] == []


def test_type_checking_import_counts_as_toplevel(tmp_path):
    root, cfg = _make(tmp_path, {
        "app/__init__.py": "", "app/low/__init__.py": "", "app/high/__init__.py": "",
        "app/low/a.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.high.b import X\n",
        "app/high/b.py": "X = 1\n"}, LAYERS)
    assert [v["kind"] for v in ca.check(root, cfg)["violations"]] == ["top-level"]


def test_relative_imports_are_resolved(tmp_path):
    root, cfg = _make(tmp_path, {
        "app/__init__.py": "", "app/low/__init__.py": "", "app/high/__init__.py": "",
        "app/high/b.py": "from ..low import a\n", "app/low/a.py": "Y = 2\n"}, LAYERS)
    res = ca.check(root, cfg)
    assert res["violations"] == [] and res["edges"] == 1  # downward is fine, and it WAS seen


def test_module_level_cycle_is_detected_and_lazy_cycle_is_not(tmp_path):
    root, cfg = _make(tmp_path, {
        "app/__init__.py": "", "app/low/__init__.py": "",
        "app/low/a.py": "from app.low import b\n", "app/low/b.py": "from app.low import a\n"}, LAYERS)
    assert ca.check(root, cfg)["cycles"] == [["app.low.a", "app.low.b"]]
    root, cfg = _make(tmp_path / "lazy", {
        "app/__init__.py": "", "app/low/__init__.py": "",
        "app/low/a.py": "from app.low import b\n", "app/low/b.py": "def f():\n    from app.low import a\n"}, LAYERS)
    assert ca.check(root, cfg)["cycles"] == []


def test_allowed_cycle_is_exempt_but_new_one_is_not(tmp_path):
    files = {"app/__init__.py": "", "app/low/__init__.py": "",
             "app/low/a.py": "from app.low import b\n", "app/low/b.py": "from app.low import a\n"}
    root, cfg = _make(tmp_path, files, LAYERS + '\n[[allowed_cycles]]\nmodules = ["app.low.b", "app.low.a"]\n')
    assert ca.check(root, cfg)["cycles"] == []


def test_main_returns_1_on_violation(tmp_path):
    root, cfg = _make(tmp_path, {
        "app/__init__.py": "", "app/low/__init__.py": "", "app/high/__init__.py": "",
        "app/low/a.py": "from app.high import b\n", "app/high/b.py": "X = 1\n"}, LAYERS)
    assert ca.main(["--root", str(root), "--layers", str(cfg)]) == 1
