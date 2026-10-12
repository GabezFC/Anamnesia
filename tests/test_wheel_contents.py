"""ANA-077 (wheel contents) + ANA-138 (HOLD: documents what the wheel puts in site-packages).

Two layers:
  * static (always runs, no build): the trees hatch will pack contain what must ship and nothing private;
  * built (marker `packaging`): inspects a real wheel. Source of the wheel, in order:
      ANAMNESIA_WHEEL=<path to .whl>   (CI `package` job builds once and passes it)
      ANAMNESIA_BUILD_WHEEL=1          (build here with `python -m build --wheel`; needs the hatchling backend,
                                        i.e. network or a populated pip cache)
    Otherwise these tests are skipped with an explicit reason.

ANA-138 decision = HOLD (do NOT rename `app`/`config`): the wheel installs the top-level names `app`, `config`,
`data`, `frontend`, `anamnesia`, `memory_gateway` into site-packages, so it can collide with unrelated
distributions that ship `app/` or `config/`. The rename touches ~every import in code, tests and docs (L effort,
P3, C=BAIXA) and breaks the documented `python -m app.main`/`app.mcp.server` entry points used by MCP client
configs. `test_wheel_top_level_names_are_the_documented_set` freezes today's surface so any change is deliberate.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
WHEEL_CFG = PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]
FORBIDDEN_SUFFIXES = (".db", ".sqlite", ".sqlite3", ".log", ".pyc", ".env", ".pem", ".key")
FORBIDDEN_NAMES = {".env", "local_settings.json", ".DS_Store"}
EXPECTED_TOP_LEVEL = {"app", "config", "anamnesia", "memory_gateway", "frontend", "data"}  # + <dist>.dist-info


def _git_tracked() -> list[str] | None:
    try:
        r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.splitlines() if r.returncode == 0 else None


# ------------------------------------------------------------------------------------------- static
def test_configured_packages_and_force_includes_exist():
    for pkg in WHEEL_CFG["packages"]:
        assert (ROOT / pkg / "__init__.py").is_file(), pkg
    for src in WHEEL_CFG["force-include"]:
        assert (ROOT / src).is_dir(), src
    assert (ROOT / "frontend" / "index.html").is_file()
    assert (ROOT / "data" / "synthetic_vault" / "MANIFEST.json").is_file()


def test_declared_top_level_surface_is_the_documented_set():
    """ANA-138 HOLD: packages + force-include destinations == EXPECTED_TOP_LEVEL (no silent growth)."""
    tops = set(WHEEL_CFG["packages"]) | {Path(dst).parts[0] for dst in WHEEL_CFG["force-include"].values()}
    assert tops == EXPECTED_TOP_LEVEL, tops ^ EXPECTED_TOP_LEVEL


def test_no_tracked_private_artifact_inside_packed_trees():
    tracked = _git_tracked()
    if tracked is None:
        pytest.skip("not a git checkout")
    trees = tuple(f"{t}/" for t in EXPECTED_TOP_LEVEL)
    bad = [f for f in tracked if f.startswith(trees)
           and (f.endswith(FORBIDDEN_SUFFIXES) or Path(f).name in FORBIDDEN_NAMES)]
    assert bad == [], bad


def test_gitignore_keeps_private_files_out_of_the_wheel():
    """hatch honours .gitignore: the private files must be ignored so they cannot be packed."""
    if _git_tracked() is None:
        pytest.skip("not a git checkout")
    for rel in ("config/local_settings.json", "benchmark.db", ".env", "data/vault_mirror/x.md", "logs/application.log"):
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT, timeout=30)
        assert r.returncode == 0, f"{rel} is not git-ignored (would be packed if present)"


def test_config_yaml_present_on_disk():
    names = {p.name for p in (ROOT / "config").glob("*.yaml")}
    assert {"connections.yaml", "models.yaml", "orchestration.yaml", "profiles.yaml"} <= names


def test_dependencies_declared_include_yaml_and_python_floor():
    deps = " ".join(PYPROJECT["project"]["dependencies"]).lower()
    assert "pyyaml" in deps  # app/* imports yaml: must not rely on a transitive dependency
    assert PYPROJECT["project"]["requires-python"] == ">=3.12"


# ------------------------------------------------------------------------------------------- built
@pytest.fixture(scope="module")
def wheel_path() -> Path:
    env = os.environ.get("ANAMNESIA_WHEEL")
    if env:
        p = Path(env)
        assert p.is_file(), f"ANAMNESIA_WHEEL={env} does not exist"
        return p
    if os.environ.get("ANAMNESIA_BUILD_WHEEL") != "1":
        pytest.skip("set ANAMNESIA_WHEEL=<whl> or ANAMNESIA_BUILD_WHEEL=1 to inspect a real wheel")
    out = Path(tempfile.mkdtemp(prefix="anamnesia-wheel-"))
    r = subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(ROOT)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        pytest.skip(f"cannot build wheel here (backend unavailable?): {(r.stdout + r.stderr)[-400:]}")
    return next(out.glob("*.whl"))


@pytest.fixture(scope="module")
def names(wheel_path) -> list[str]:
    with zipfile.ZipFile(wheel_path) as z:
        return z.namelist()


@pytest.mark.packaging
def test_wheel_top_level_names_are_the_documented_set(names):
    tops = {n.split("/")[0] for n in names}
    dist_info = {t for t in tops if t.endswith(".dist-info")}
    assert len(dist_info) == 1
    assert tops - dist_info == EXPECTED_TOP_LEVEL, tops ^ EXPECTED_TOP_LEVEL


@pytest.mark.packaging
def test_wheel_ships_frontend_vault_and_yaml(names):
    s = set(names)
    assert "frontend/index.html" in s
    assert any(n.startswith("frontend/css/") for n in names)
    assert "data/synthetic_vault/MANIFEST.json" in s
    assert sum(1 for n in names if n.startswith("data/synthetic_vault/") and n.endswith(".md")) > 100
    for y in (ROOT / "config").glob("*.yaml"):
        assert f"config/{y.name}" in s, y.name
    assert "config/local_settings.example.json" in s
    assert "anamnesia/__init__.py" in s and "app/mcp/server.py" in s


@pytest.mark.packaging
def test_wheel_has_no_private_or_generated_files(names):
    bad = [n for n in names if n.endswith(FORBIDDEN_SUFFIXES) or Path(n).name in FORBIDDEN_NAMES
           or "__pycache__" in n or n.startswith(("logs/", "data/vault_mirror/", "data/saved_context/"))]
    assert bad == [], bad
    assert not [n for n in names if n.startswith("tests/") or n.startswith("scripts/") or n.startswith("docs/")]


@pytest.mark.packaging
def test_wheel_metadata(wheel_path):
    with zipfile.ZipFile(wheel_path) as z:
        meta = next(z.read(n).decode() for n in z.namelist() if n.endswith(".dist-info/METADATA"))
        eps = next(z.read(n).decode() for n in z.namelist() if n.endswith("entry_points.txt"))
    assert "Requires-Python: >=3.12" in meta
    assert "Requires-Dist: PyYAML==" in meta
    assert "Provides-Extra: terminal" in meta and "Provides-Extra: dev" in meta
    assert "anamnesia = anamnesia.cli:main" in eps


@pytest.mark.packaging
def test_unpacked_wheel_resources_and_cli_work_outside_the_repo(wheel_path, tmp_path):
    """Unzip the wheel next to nothing else and run from there: resources resolve via the package, not the repo."""
    dest = tmp_path / "site"
    with zipfile.ZipFile(wheel_path) as z:
        z.extractall(dest)
    code = (
        "import importlib.resources as r, sys, pathlib;"
        "import config.paths as p;"
        "assert p.PACKAGE_ROOT == pathlib.Path(sys.argv[1]).resolve(), p.PACKAGE_ROOT;"
        "assert r.files('config').joinpath('models.yaml').is_file();"
        "assert (p.PACKAGE_ROOT / 'frontend' / 'index.html').is_file();"
        "assert (p.PACKAGE_ROOT / 'data' / 'synthetic_vault' / 'MANIFEST.json').is_file();"
        "import anamnesia.cli as c; assert c.main(['version']) == 0"
    )
    env = {**os.environ, "PYTHONPATH": str(dest), "ANAMNESIA_HOME": str(tmp_path / "home")}
    r = subprocess.run([sys.executable, "-c", code, str(dest)], cwd=tmp_path, env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "anamnesia 0." in r.stdout
