"""ANA-040 / ANA-042: UI challenge (cookie) and human confirmation for shell sessions.

Modes (env, default `enforce` since ANAM-001; `warn` = log only, `off` = disabled):
  MG_TOKEN_COOKIE=warn|enforce|off   /config/token requires the HttpOnly SameSite=Strict cookie issued on `GET /`
  MG_SHELL_CONFIRM=warn|enforce|off  shell/PowerShell session creation requires header X-MG-Confirm == cookie value
Rollback: set the variable to `off`.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets

COOKIE_NAME = "mg_ui"
CONFIRM_HEADER = "x-mg-confirm"
SHELL_PROFILES = {"shell", "powershell", "pwsh", "cmd", "bash"}
DEFAULT_MODE = "enforce"  # ANAM-001 (D-2): was "warn"; MG_TOKEN_COOKIE/MG_SHELL_CONFIRM=warn restores old behaviour
_log = logging.getLogger("anamnesia.security")
_UI_SECRET = secrets.token_urlsafe(24)  # per-process; issued only with the page load


def mode(var: str) -> str:
    """ANAM-001: default is `enforce` (fail closed). Transition: set the variable to `warn` or `off`."""
    v = os.environ.get(var, DEFAULT_MODE).strip().lower()
    return v if v in {"warn", "enforce", "off"} else DEFAULT_MODE


def ui_cookie_value() -> str:
    return _UI_SECRET


def has_ui_cookie(request) -> bool:
    got = request.cookies.get(COOKIE_NAME, "")
    return bool(got) and hmac.compare_digest(got, _UI_SECRET)


def check_token_bootstrap(request) -> bool:
    """True if /config/token may be served."""
    m = mode("MG_TOKEN_COOKIE")
    if m == "off" or has_ui_cookie(request):
        return True
    _log.warning("config_token without UI cookie (mode=%s)", m)
    return m != "enforce"


def check_shell_confirm(request, profile_id: str) -> bool:
    """True if a session for `profile_id` may be created."""
    if (profile_id or "").lower() not in SHELL_PROFILES:
        return True
    m = mode("MG_SHELL_CONFIRM")
    if m == "off":
        return True
    got = request.headers.get(CONFIRM_HEADER, "")
    if got and hmac.compare_digest(got, _UI_SECRET):
        return True
    _log.warning("shell session without confirm (mode=%s)", m)
    return m != "enforce"


def check_confirm_header(request, action: str = "") -> bool:
    """True if a destructive action (e.g. worktree removal) may proceed: valid X-MG-Confirm, or the
    MG_SHELL_CONFIRM mode is not `enforce`."""
    m = mode("MG_SHELL_CONFIRM")
    if m == "off":
        return True
    got = request.headers.get(CONFIRM_HEADER, "")
    if got and hmac.compare_digest(got, _UI_SECRET):
        return True
    _log.warning("%s without confirm (mode=%s)", action or "action", m)
    return m != "enforce"
