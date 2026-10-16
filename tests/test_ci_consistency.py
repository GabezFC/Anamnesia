"""ANAM-022/023/024: pyproject <-> requirements <-> CI <-> docker/packaging stay mirrored. All offline.

Cited by pyproject.toml, requirements.txt and requirements-dev.txt ("fails on any divergence").
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

try:                                     # py>=3.11 (project requires >=3.12)
    import tomllib
except ImportError:                      # pragma: no cover
    tomllib = None  # type: ignore[assignment]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _req_lines(name: str) -> list[str]:
    out = []
    for raw in (ROOT / name).read_text(encoding="utf-8").splitlines():
        line = raw.split(" #")[0].strip() if not raw.lstrip().startswith("#") else ""
        if line and not line.startswith("-r"):
            out.append(line)
    return out


def _norm(specs: list[str]) -> list[str]:
    return sorted(s.replace(" ", "").lower() for s in specs)


def _ci() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _ci_text() -> str:
    return (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


# ------------------------------------------------------------------ pyproject <-> requirements (ANA-121)
def test_requirements_mirror_pyproject_dependencies():
    assert _norm(_req_lines("requirements.txt")) == _norm(_pyproject()["project"]["dependencies"])


def test_requirements_dev_mirror_pyproject_dev_extra():
    dev = _pyproject()["project"]["optional-dependencies"]["dev"]
    assert _norm(_req_lines("requirements-dev.txt")) == _norm(dev)


def test_requirements_dev_includes_runtime_requirements_and_timeout_plugin():
    text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^-r requirements\.txt\s*$", text, re.M)
    assert any(s.startswith("pytest-timeout==") for s in _req_lines("requirements-dev.txt"))


def test_dev_dependencies_are_pinned_exactly():
    for name in ("requirements.txt", "requirements-dev.txt"):
        for spec in _req_lines(name):
            assert "==" in spec, f"{name}: {spec} is not pinned with =="


# ------------------------------------------------------------------ CI workflow (ANAM-022)
def test_ci_yaml_is_valid_and_has_expected_jobs():
    ci = _ci()
    assert {"test", "docker", "e2e-browser"} <= set(ci["jobs"])


def test_ci_test_step_hardening_flags():
    text = _ci_text()
    for flag in ("--block-network", "--shuffle-seed=", "--timeout="):
        assert flag in text, f"ci.yml pytest step lacks {flag}"
    assert "GITHUB_STEP_SUMMARY" in text, "shuffle seed must be registered in the job summary"


def test_ci_runs_generated_doc_checks():
    text = _ci_text()
    assert "scripts/gen_config_reference.py --check" in text
    assert "scripts/gen_interface_docs.py --check" in text


def test_ci_pytest_flags_exist_in_conftest():
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    for opt in ("--block-network", "--shuffle-seed"):
        assert opt in conftest


def test_ci_python_matrix_matches_requires_python_and_docker_matrix():
    ci = _ci()
    test_py = [str(v) for v in ci["jobs"]["test"]["strategy"]["matrix"]["python"]]
    docker_py = [str(v) for v in ci["jobs"]["docker"]["strategy"]["matrix"]["python"]]
    assert test_py == docker_py
    requires = _pyproject()["project"]["requires-python"]
    floor = tuple(int(x) for x in re.search(r">=\s*(\d+)\.(\d+)", requires).groups())
    assert min(tuple(int(x) for x in v.split(".")) for v in test_py) >= floor


def test_ci_uses_requirements_files_that_exist():
    text = _ci_text()
    for name in set(re.findall(r"-r (requirements[\w-]*\.txt)", text)):
        assert (ROOT / name).is_file(), name


def test_coverage_fail_under_is_a_valid_ratchet_value():
    fu = _pyproject()["tool"]["coverage"]["report"]["fail_under"]
    assert isinstance(fu, (int, float)) and 0 <= fu <= 100


# ------------------------------------------------------------------ env docs (ANAM-023)
def test_env_reference_fresh_and_env_example_lists_every_user_var():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import gen_config_reference as g
    finally:
        sys.path.pop(0)
    found = g.collect()
    cur = (ROOT / "docs" / "ENVIRONMENT_REFERENCE.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert cur == g.render(found), "run scripts/gen_config_reference.py"
    listed = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]{2,})=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    missing = sorted(n for n in found if g.kind_of(n) == "user" and n not in listed)
    assert not missing, f".env.example lacks user vars: {missing}"


def test_env_example_has_no_secret_values():
    secretish = re.compile(r"^[ \t]*(?!#)[A-Z0-9_]*(_KEY|_TOKEN|_SECRET|_PASSWORD)=[ \t]*\S", re.M)
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not secretish.search(text), "uncommented secret-like var with a value in .env.example"


# ------------------------------------------------------------------ Docker allow-list (ANAM-024)
def _glob_to_re(pat: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if pat.startswith("**", i):
            out += ".*"
            i += 2
            continue
        out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
        i += 1
    return re.compile("^" + out + "$")


def _dockerignore_rules() -> list[tuple[bool, re.Pattern[str]]]:
    rules = []
    for raw in (ROOT / "Dockerfile.test.dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        rules.append((neg, _glob_to_re(line.lstrip("!").strip("/"))))
    return rules


def sent_to_context(path: str) -> bool:
    """Moby semantics: last matching pattern wins; a pattern matching a parent directory matches the path."""
    parts = path.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    sent = True
    for neg, rx in _dockerignore_rules():
        if any(rx.match(p) for p in prefixes):
            sent = neg
    return sent


def test_dockerignore_is_an_allow_list():
    first = [ln.strip() for ln in (ROOT / "Dockerfile.test.dockerignore").read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.strip().startswith("#")][0]
    assert first == "*"


@pytest.mark.parametrize("path", [
    "benchmark.db", "benchmark.db-wal", "anamnesia.db", "anamnesia.db.bak-v0", "data/anamnesia.db.bak-v0",
    "backups/x.zip", "data/backups/x.zip", "data/vault_mirror/a.md", "data/terminal_mcp/s.json",
    ".delegation/t.json", "Python/python.exe", "_studio/x.html", "config/local_settings.json",
    ".env", ".env.local", "app/__pycache__/x.pyc", "data/onda4e_bench.db", "reports/x.md", ".git/HEAD",
    ".venv/Scripts/python.exe", "integrations/hermes/hermes_home/state.db", "some_new_root_file.txt",
])
def test_dockerignore_excludes_sensitive_and_local_state(path):
    assert not sent_to_context(path), f"{path} would be sent to the Docker build context"


@pytest.mark.parametrize("path", [
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "app/main.py", "config/policy.yaml",
    "config/local_settings.example.json", "tests/conftest.py", "scripts/gen_config_reference.py",
    "data/synthetic_vault/index.md", "benchmark/synthetic_questions.json", "docs/INTERFACES.md",
    "frontend/index.html", ".env.example", "Dockerfile.test", "AGENTS.md", "CLAUDE.md",
])
def test_dockerignore_keeps_what_the_suite_needs(path):
    assert sent_to_context(path), f"{path} is required by the suite but excluded"


def test_dockerignore_covers_every_tracked_top_level_entry():
    import subprocess
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.skip("git ls-files unavailable")
    # data/<x> files other than synthetic_vault are intentionally not sent (tracked backup db etc.).
    lost = [p for p in out.stdout.splitlines()
            if p and not sent_to_context(p)
            and not p.endswith((".db.bak-v0", ".gitkeep")) and not p.startswith(("data/", "Python/", "_studio/"))]
    assert not lost, f"tracked files missing from the test image context: {lost[:20]}"


# ------------------------------------------------------------------ build_exe (ANAM-024)
def test_build_exe_does_not_bundle_local_settings(tmp_path):
    spec = importlib.util.spec_from_file_location("mg_build_exe", ROOT / "packaging" / "build_exe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    staged = mod.stage_config(tmp_path)
    assert (staged / "policy.yaml").is_file()
    assert not list(staged.rglob("local_settings.json"))
    assert (staged / "local_settings.example.json").is_file()
    src = (ROOT / "packaging" / "build_exe.py").read_text(encoding="utf-8")
    assert '"--add-data", f"{ROOT / src}' not in src, "raw ROOT/config must not be added directly"
