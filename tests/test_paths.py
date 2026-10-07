"""config/paths.py: user data dir resolution (ANAMNESIA_HOME, dev default, installed layout)."""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from config import paths


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ANAMNESIA_HOME", raising=False)


def test_dev_default_is_repo_root_and_unchanged():
    assert paths.user_data_dir() == paths.PACKAGE_ROOT
    assert paths.env_file_path() == paths.PACKAGE_ROOT / ".env"
    assert paths.benchmark_db_path() == paths.PACKAGE_ROOT / "benchmark.db"
    assert paths.logs_dir() == paths.PACKAGE_ROOT / "logs"
    assert paths.data_dir() == paths.PACKAGE_ROOT / "data"
    assert paths.local_settings_path() == paths.PACKAGE_ROOT / "config" / "local_settings.json"


def test_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "h"))
    home = (tmp_path / "h").resolve()
    assert paths.user_data_dir() == home
    assert paths.env_file_path() == home / ".env"
    assert paths.benchmark_db_path() == home / "benchmark.db"
    assert paths.logs_dir() == home / "logs"
    assert paths.data_dir() == home / "data"
    assert paths.local_settings_path() == home / "local_settings.json"
    assert not home.exists()  # pure resolution, nothing created


def test_installed_layout_detection(tmp_path):
    site = tmp_path / "venv" / "Lib" / "site-packages"
    site.mkdir(parents=True)
    assert paths.is_installed_layout(site)
    (site / ".git").mkdir()
    assert not paths.is_installed_layout(site)
    assert not paths.is_installed_layout(tmp_path / "checkout")


def test_installed_layout_uses_platform_dir(monkeypatch, tmp_path):
    site = tmp_path / "venv" / "site-packages"
    site.mkdir(parents=True)
    monkeypatch.setattr(paths, "PACKAGE_ROOT", site)
    monkeypatch.setattr(paths, "platform_data_dir", lambda: tmp_path / "userdata")
    assert paths.user_data_dir() == tmp_path / "userdata"
    assert paths.env_file_path() == tmp_path / "userdata" / ".env"
    assert paths.local_settings_path() == tmp_path / "userdata" / "local_settings.json"
    # ANAMNESIA_HOME still wins over the installed default
    monkeypatch.setenv("ANAMNESIA_HOME", str(tmp_path / "x"))
    assert paths.user_data_dir() == (tmp_path / "x").resolve()


@pytest.mark.parametrize("plat,env,expected_tail", [
    ("win32", {"LOCALAPPDATA": "L"}, ("L", "Anamnesia")),
    ("linux", {"XDG_DATA_HOME": "X"}, ("X", "anamnesia")),
])
def test_platform_dirs(monkeypatch, plat, env, expected_tail):
    monkeypatch.setattr(sys, "platform", plat)
    for k in ("LOCALAPPDATA", "XDG_DATA_HOME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert paths.platform_data_dir() == Path(*expected_tail)


def test_darwin_dir(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert paths.platform_data_dir() == Path.home() / "Library" / "Application Support" / "Anamnesia"


def test_import_creates_nothing(tmp_path):
    home = tmp_path / "never"
    code = "import config, config.paths, config.benchmark, config.retrieval, app.services.metrics, app.services.security"
    import os
    env = dict(os.environ, ANAMNESIA_HOME=str(home))
    r = subprocess.run([sys.executable, "-c", code], cwd=str(paths.PACKAGE_ROOT), env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not home.exists()


def test_override_routes_modules(tmp_path):
    home = tmp_path / "h2"
    code = ("from app.services import security, metrics; from config.benchmark import BenchmarkConfig;"
            "print(security.ENV_PATH); print(metrics.LOG_DIR); print(BenchmarkConfig().db_path)")
    import os
    r = subprocess.run([sys.executable, "-c", code], cwd=str(paths.PACKAGE_ROOT),
                       env={**{k: v for k, v in os.environ.items() if k != "DB_PATH"}, "ANAMNESIA_HOME": str(home)},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = [Path(x) for x in r.stdout.split("\n") if x.strip()]
    h = home.resolve()
    assert out[0] == h / ".env" and out[1] == h / "logs" and out[2] == h / "benchmark.db"
