import subprocess
import sys

from anamnesia import __version__, cli


def test_version(capsys):
    assert cli.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == f"anamnesia {__version__}"


def test_doctor_no_secret_and_exit0(capsys, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "SECRET123")
    monkeypatch.setenv("MG_LOCAL_TOKEN", "TOKEN456")
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "SECRET123" not in out and "TOKEN456" not in out
    assert "TYPESAFE_API_KEY" in out and "yes" in out


def test_doctor_fails_without_vault(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_GATEWAY_VAULT", str(tmp_path / "missing"))
    assert cli.main(["doctor"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_doctor_fails_on_old_python(monkeypatch, capsys):
    monkeypatch.setattr(cli, "MIN_PYTHON", (99, 0))
    assert cli.main(["doctor"]) == 1


def test_doctor_offline(monkeypatch, capsys):
    import socket

    def boom(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    assert cli.main(["doctor"]) == 0


def test_start_reuses_app_main(monkeypatch):
    import app.main as m
    called = []
    monkeypatch.setattr(m, "main", lambda: called.append(1))
    assert cli.main(["start"]) == 0 and called == [1]


def test_python_dash_m():
    r = subprocess.run([sys.executable, "-m", "anamnesia", "version"], capture_output=True, text=True)
    assert r.returncode == 0 and __version__ in r.stdout
