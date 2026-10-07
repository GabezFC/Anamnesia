"""Local-only write protection for the REST API (§5.4, §3 da proposta 2026-09-28).

Before this module, `app/main.py` bound `0.0.0.0` with no authentication at all: any machine on
the LAN could trigger a benchmark run, mark feedback, or — once the configuration page (§3) landed
— write model API keys and change `vault_path` through the dashboard. Every endpoint that changes
server state now requires ALL of:

  1. the TCP client is 127.0.0.1/::1 (loopback only, independent of what MG_HOST the server bound
     to — a server started with MG_HOST=0.0.0.0 for LAN access still refuses writes from the LAN).
  2. Origin/Referer, when the browser sends one, name this same origin (a minimal CSRF guard: a
     page on the LAN cannot trick a local browser into POSTing here). Absent for non-browser
     callers (curl, the CLI's own HTTP calls), which is why a missing header is allowed through —
     the loopback + token checks are what actually gates the request.
  3. header `X-MG-Token` matches a token generated on first start and stored in `.env`
     (`MG_LOCAL_TOKEN`). Never logged. The frontend obtains it once from GET /config/token, which
     is itself loopback-only.
"""
from __future__ import annotations

import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app.services.envfile import set_env_var
from config.paths import env_file_path

ENV_PATH = env_file_path()
LOCAL_HOSTS = {"127.0.0.1", "::1"}
TOKEN_ENV_VAR = "MG_LOCAL_TOKEN"


# Env vars the interactive configuration page (§3) is allowed to write. A whitelist, not a
# free-form key name, so the endpoint can never be used to overwrite an unrelated .env line.
MODEL_KEY_ENV_VARS = (
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_COMPAT_API_KEY",
    "TYPESAFE_API_KEY",
)


def mask_secret(value: str | None) -> str | None:
    """Last 4 characters only (§3: "mostrar só os últimos 4 caracteres"); None if unset.

    The masked prefix is a fixed length, not proportional to the real secret's length, so the
    displayed value never leaks how long the underlying key is.
    """
    if not value:
        return None
    return f"{'•' * 8}{value[-4:]}" if len(value) >= 4 else "•" * len(value)


def get_or_create_local_token() -> str:
    """Read `MG_LOCAL_TOKEN` from the environment, or mint and persist one on first use.

    Lazy on purpose: works whether or not `app.main`'s startup already called it (tests build the
    FastAPI app directly, without that lifespan hook).
    """
    token = os.environ.get(TOKEN_ENV_VAR)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    set_env_var(ENV_PATH, TOKEN_ENV_VAR, token)
    os.environ[TOKEN_ENV_VAR] = token
    return token


def is_local_client(request: Request) -> bool:
    client = request.client
    return bool(client) and client.host in LOCAL_HOSTS


def _same_origin(request: Request, header_value: str | None) -> bool:
    if not header_value:
        return True  # nothing sent: cannot check, and non-browser callers never send Origin
    own_host = request.headers.get("host", "")
    sent_host = urlsplit(header_value).netloc
    return sent_host == own_host


def require_localhost(request: Request) -> None:
    """Loopback-only, no token: for the bootstrap endpoint that hands the token out."""
    if not is_local_client(request):
        raise HTTPException(403, "acesso restrito a 127.0.0.1/::1")


def require_local_write(request: Request) -> None:
    """Full guard for endpoints that change server state, files, or secrets."""
    if not is_local_client(request):
        raise HTTPException(403, "acesso restrito a 127.0.0.1/::1")
    if not _same_origin(request, request.headers.get("origin")):
        raise HTTPException(403, "Origin não corresponde a este servidor")
    if not _same_origin(request, request.headers.get("referer")):
        raise HTTPException(403, "Referer não corresponde a este servidor")
    expected = get_or_create_local_token()
    got = request.headers.get("x-mg-token")
    if not got or not secrets.compare_digest(got, expected):
        raise HTTPException(403, "X-MG-Token ausente ou inválido")
