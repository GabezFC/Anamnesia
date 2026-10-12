"""ANA-040 / ANA-041 / ANA-042 / ANA-043."""
import pytest
from fastapi.testclient import TestClient

from app.services import ui_challenge
from app.services.obsidian import ObsidianVault, VaultAccessError


@pytest.mark.parametrize("p", ["x.md::$DATA", "x.md:stream", "\\\\?\\C:\\a.md", "CON.md", "dir/NUL", "aux.txt"])
def test_ana043_vault_read_rejects(tmp_path, p):
    (tmp_path / "x.md").write_text("ok", encoding="utf-8")
    v = ObsidianVault(tmp_path)
    with pytest.raises(VaultAccessError):
        v.read(p)


def test_ana043_normal_read_ok(tmp_path):
    (tmp_path / "x.md").write_text("ok", encoding="utf-8")
    assert ObsidianVault(tmp_path).read("x.md") == "ok"


class _Req:
    def __init__(self, cookies=None, headers=None):
        self.cookies = cookies or {}
        self.headers = headers or {}


def test_ana040_cookie_modes(monkeypatch):
    monkeypatch.setenv("MG_TOKEN_COOKIE", "enforce")
    assert not ui_challenge.check_token_bootstrap(_Req())
    assert ui_challenge.check_token_bootstrap(_Req({ui_challenge.COOKIE_NAME: ui_challenge.ui_cookie_value()}))
    monkeypatch.setenv("MG_TOKEN_COOKIE", "warn")
    assert ui_challenge.check_token_bootstrap(_Req())
    monkeypatch.setenv("MG_TOKEN_COOKIE", "off")
    assert ui_challenge.check_token_bootstrap(_Req())


def test_ana042_shell_confirm(monkeypatch):
    monkeypatch.setenv("MG_SHELL_CONFIRM", "enforce")
    assert not ui_challenge.check_shell_confirm(_Req(), "shell")
    assert ui_challenge.check_shell_confirm(_Req(headers={"x-mg-confirm": ui_challenge.ui_cookie_value()}), "shell")
    assert ui_challenge.check_shell_confirm(_Req(), "claude")  # non-shell profiles unaffected
    monkeypatch.setenv("MG_SHELL_CONFIRM", "warn")
    assert ui_challenge.check_shell_confirm(_Req(), "shell")


def test_ana040_http_enforce(monkeypatch):
    from app.main import app
    monkeypatch.setenv("MG_TOKEN_COOKIE", "enforce")
    c = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    assert c.get("/config/token").status_code == 403
    r = c.get("/")  # issues the cookie
    assert r.status_code == 200
    assert c.get("/config/token").status_code == 200
    assert c.get("/config/shell-confirm").json()["confirm"] == ui_challenge.ui_cookie_value()


def test_ana041_metrics_only(tmp_path, monkeypatch):
    from app.database.db import Database
    monkeypatch.setenv("ANAMNESIA_METRICS_ONLY", "1")
    db = Database(tmp_path / "b.db")
    row = {"run_id": "r1", "query": "q", "pipeline": "baseline", "context": "SEGREDO", "created_at": 1.0}
    db.save_run(row)
    got = db.get_run("r1")
    assert got is not None and not got.get("context")
