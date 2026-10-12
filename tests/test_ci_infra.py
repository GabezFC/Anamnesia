"""Test-infrastructure guarantees: ANA-084 (isolation), ANA-105 (network block), ANA-127 (markers),
ANA-129 (shuffle), ANA-130 (no sys.path hack required). All offline."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

import ci_support
from ci_support import NetworkBlocked

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


# ---------------------------------------------------------------------------------------- ANA-084
def test_anamnesia_home_is_isolated_for_the_whole_session():
    from config import paths
    home = Path(os.environ["ANAMNESIA_HOME"]).resolve()
    assert home.name.startswith("anamnesia-tests-home-")
    assert ROOT not in home.parents and home != ROOT
    assert paths.user_data_dir() == home
    for p in (paths.benchmark_db_path(), paths.env_file_path(), paths.logs_dir(), paths.data_dir(),
              paths.saved_context_dir()):
        assert ROOT not in p.resolve().parents, p


def test_default_benchmark_config_does_not_point_into_the_repo():
    from config.benchmark import BenchmarkConfig
    db = Path(BenchmarkConfig().db_path).resolve()
    assert ROOT not in db.parents, f"BenchmarkConfig default db is inside the repo: {db}"


def test_fingerprint_detects_create_modify_delete(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "a.txt").write_text("1")
    (tmp_path / "benchmark.db").write_text("x")
    before = ci_support.fingerprint(tmp_path)
    assert ci_support.diff_fingerprints(before, ci_support.fingerprint(tmp_path)) == []
    (tmp_path / "data" / "a.txt").write_text("22")          # modified
    (tmp_path / "data" / "b.txt").write_text("n")           # created
    (tmp_path / "benchmark.db").unlink()                    # deleted
    (tmp_path / "data" / "__pycache__").mkdir()
    (tmp_path / "data" / "__pycache__" / "x.pyc").write_text("ignored")
    changes = ci_support.diff_fingerprints(before, ci_support.fingerprint(tmp_path))
    assert changes == ["deleted: benchmark.db", "modified: data/a.txt", "created: data/b.txt"]


def _run_pytest_in_tmp_project(tmp_path: Path, test_body: str, *args: str) -> subprocess.CompletedProcess:
    """Mini project that reuses THIS conftest + ci_support (so the real hooks are exercised)."""
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    shutil.copy(TESTS / "conftest.py", proj / "tests" / "conftest.py")
    shutil.copy(TESTS / "ci_support.py", proj / "tests" / "ci_support.py")
    (proj / "tests" / "test_probe.py").write_text(textwrap.dedent(test_body), encoding="utf-8")
    (proj / "pytest.ini").write_text("[pytest]\ntestpaths = tests\nmarkers =\n  network: x\n  e2e: x\n  slow: x\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("ANAMNESIA_SHUFFLE_SEED", None)
    env.pop("ANAMNESIA_BLOCK_NETWORK", None)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=proj, env=env, capture_output=True, text=True, timeout=120)


@pytest.mark.integration
def test_tree_guard_strict_fails_when_suite_touches_the_repo(tmp_path):
    body = """
    from pathlib import Path
    def test_writes_into_repo():
        (Path(__file__).resolve().parents[1] / "benchmark.db").write_text("oops")
    """
    r = _run_pytest_in_tmp_project(tmp_path, body, "--tree-guard=strict")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "created: benchmark.db" in r.stderr
    warn = _run_pytest_in_tmp_project(tmp_path / "w", body)  # default = warn: reported but exit 0
    assert warn.returncode == 0 and "WARNING ANA-084" in warn.stderr


@pytest.mark.integration
def test_tree_guard_strict_passes_on_a_clean_run(tmp_path):
    r = _run_pytest_in_tmp_project(tmp_path, "def test_ok():\n    assert True\n", "--tree-guard=strict")
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------------------- ANA-105
def test_block_network_rejects_external_connect_and_dns():
    orig_connect, orig_dns = socket.socket.connect, socket.getaddrinfo
    with ci_support.block_network():
        with pytest.raises(NetworkBlocked):
            socket.create_connection(("203.0.113.7", 80), timeout=0.2)
        with pytest.raises(NetworkBlocked):
            socket.socket().connect_ex(("198.51.100.9", 443))
        with pytest.raises(NetworkBlocked):
            socket.getaddrinfo("api.example.com", 443)
    # restored afterwards: the originals are back
    assert socket.socket.connect is orig_connect and socket.getaddrinfo is orig_dns


def test_block_network_allows_loopback_and_restores():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        with ci_support.block_network():
            c = socket.create_connection(("127.0.0.1", port), timeout=2)
            c.close()
            socket.getaddrinfo("localhost", port)
    finally:
        srv.close()


@pytest.mark.parametrize("host,loop", [("127.0.0.1", True), ("localhost", True), ("::1", True), ("[::1]", True),
                                       ("127.9.9.9", True), ("10.0.0.5", False), ("8.8.8.8", False),
                                       ("api.anthropic.com", False)])
def test_is_loopback_host(host, loop):
    assert ci_support.is_loopback_host(host) is loop


@pytest.mark.integration
def test_block_network_flag_makes_external_attempt_a_failure(tmp_path):
    body = """
    import socket
    def test_phones_home():
        socket.create_connection(("203.0.113.7", 80), timeout=0.2)
    import pytest
    @pytest.mark.network
    def test_exempt_marker_skips_the_block():
        pass
    """
    r = _run_pytest_in_tmp_project(tmp_path, body, "--block-network")
    assert r.returncode == 1
    assert "NetworkBlocked" in r.stdout and "1 failed, 1 passed" in r.stdout, r.stdout


# ---------------------------------------------------------------------------------------- ANA-129
def test_resolve_seed():
    assert ci_support.resolve_seed(None) is None
    assert ci_support.resolve_seed("") is None
    assert ci_support.resolve_seed("42") == 42
    assert isinstance(ci_support.resolve_seed("random"), int)


def test_shuffled_is_deterministic_per_seed_and_permutes():
    class It:
        def __init__(self, m, n):
            self.module = type("M", (), {"__name__": m})
            self.n = n
    items = [It(f"m{i // 5}", i) for i in range(50)]
    a = ci_support.shuffled(items, 7)
    assert [x.n for x in a] == [x.n for x in ci_support.shuffled(items, 7)]
    assert [x.n for x in a] != [x.n for x in ci_support.shuffled(items, 8)]
    assert sorted(x.n for x in a) == list(range(50))
    # module groups stay contiguous
    mods = [x.module.__name__ for x in a]
    assert all(mods.index(m) + mods.count(m) == len(mods) - mods[::-1].index(m) for m in set(mods))


@pytest.mark.integration
def test_shuffle_seed_flag_reorders_and_is_reproducible(tmp_path):
    body = "\n".join(f"def test_t{i:02d}():\n    pass\n" for i in range(12))
    runs = iter(range(100))

    def order(seed):
        r = _run_pytest_in_tmp_project(tmp_path / f"s{next(runs)}", body, "--shuffle-seed=%s" % seed, "-vv")
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"shuffle seed={seed}" in r.stdout
        return [ln.split("::")[1].split()[0] for ln in r.stdout.splitlines() if "::test_t" in ln]
    assert order(11) == order(11)
    assert order(11) != order(12)
    assert sorted(order(11)) == [f"test_t{i:02d}" for i in range(12)]


# ---------------------------------------------------------------------------------------- ANA-127
def test_auto_markers_mapping():
    assert ci_support.auto_markers_for("tests/e2e/test_workspace_e2e.py") == ["e2e", "slow"]
    assert ci_support.auto_markers_for("tests\\test_pty_posix.py") == ["posix_only"]
    assert ci_support.auto_markers_for("tests/test_terminals_jobobject.py") == ["windows_only"]
    assert ci_support.auto_markers_for("tests/test_paths.py") == []


def test_marker_deselection_works_via_collect_only():
    """`-m "not slow"` must be a valid expression with every marker registered (--strict-markers)."""
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                        "-m", "not slow and not e2e and not windows_only", "tests/e2e", "tests/test_pty_posix.py",
                        "tests/test_terminals_jobobject.py"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 5), r.stdout + r.stderr  # 5 = nothing selected, still a valid selection
    assert "test_workspace_e2e.py::" not in r.stdout
    assert "test_terminals_jobobject.py::" not in r.stdout
    assert "unknown" not in (r.stdout + r.stderr).lower()


# ---------------------------------------------------------------------------------------- ANA-130
@pytest.mark.integration
def test_conftest_honours_no_path_hack(tmp_path):
    """With ANAMNESIA_TEST_NO_PATH_HACK=1 conftest must NOT put the repo root on sys.path itself."""
    proj = tmp_path / "proj"
    (proj / "tests").mkdir(parents=True)
    shutil.copy(TESTS / "conftest.py", proj / "tests" / "conftest.py")
    shutil.copy(TESTS / "ci_support.py", proj / "tests" / "ci_support.py")
    (proj / "tests" / "test_p.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "def test_p():\n    root = str(Path(__file__).resolve().parents[1])\n"
        "    assert root not in sys.path\n", encoding="utf-8")
    env = {**os.environ, "ANAMNESIA_TEST_NO_PATH_HACK": "1", "PYTHONPATH": str(ROOT)}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(proj)],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert tempfile.gettempdir()  # (keeps `tempfile` import honest for static checkers)
