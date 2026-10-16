"""ANAM-001: token/shell chain is closed by default (fail closed); `warn`/`off` remain as transition modes."""
import pytest
from fastapi.testclient import TestClient

from app.services import ui_challenge


@pytest.fixture
def default_modes(monkeypatch):
    monkeypatch.delenv("MG_TOKEN_COOKIE", raising=False)
    monkeypatch.delenv("MG_SHELL_CONFIRM", raising=False)


def test_default_mode_is_enforce(default_modes):
    assert ui_challenge.mode("MG_TOKEN_COOKIE") == "enforce"
    assert ui_challenge.mode("MG_SHELL_CONFIRM") == "enforce"


def test_invalid_value_falls_back_to_enforce(monkeypatch):
    monkeypatch.setenv("MG_SHELL_CONFIRM", "banana")
    assert ui_challenge.mode("MG_SHELL_CONFIRM") == "enforce"


def test_process_without_cookie_gets_no_token_by_default(default_modes):
    from app.main import app
    c = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    assert c.get("/config/token").status_code == 403          # a child process / PTY has no cookie
    assert c.get("/config/shell-confirm").status_code == 403
    c.get("/")                                                  # the SPA load issues the HttpOnly cookie
    assert c.get("/config/token").status_code == 200
    assert c.get("/config/shell-confirm").status_code == 200


def test_shell_session_blocked_without_confirm_by_default(default_modes):
    class R:
        cookies, headers = {}, {}
    assert not ui_challenge.check_shell_confirm(R(), "shell")
    R.headers = {"x-mg-confirm": ui_challenge.ui_cookie_value()}
    assert ui_challenge.check_shell_confirm(R(), "shell")


def test_transition_mode_warn_still_allows(monkeypatch):
    monkeypatch.setenv("MG_SHELL_CONFIRM", "warn")
    class R:
        cookies, headers = {}, {}
    assert ui_challenge.check_shell_confirm(R(), "shell")
