"""ANA-216/ANA-217: MCP -> REST bridge (stdio MCP on the host, Gateway in a container or on another host).

    MG_MCP_BRIDGE_URL=http://127.0.0.1:8000   # opt-in; unset (default) = in-process gateway, nothing changes
    MG_MCP_TOKEN=<token>                      # optional Bearer; sent as `Authorization: Bearer ...`

Why a token: inside Docker the server binds 0.0.0.0 and the published port reaches it from the bridge-network IP,
not from loopback, so `app.services.security.read_auth_required` demands `X-MG-Token` or `Authorization: Bearer`
for reads. The token is OPTIONAL because a plain local REST on loopback needs none. It is read from the
environment only, never logged, never put in an error message.

Only `memory_search` is bridged (POST /memory/search); other tools keep needing the in-process gateway.
"""
from __future__ import annotations

import os

import httpx

from app.services.egress import check_egress
from app.services.offline import ensure_online

COMPACT_METRICS = ("pipeline", "context_tokens", "total_tokens_spent", "total_latency_ms",
                   "result_cache_hit", "error")


def bridge_url() -> str | None:
    v = os.environ.get("MG_MCP_BRIDGE_URL", "").strip()
    return v.rstrip("/") or None


def auth_headers(token: str | None = None) -> dict:
    tok = (os.environ.get("MG_MCP_TOKEN", "") if token is None else token).strip()
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def bridge_search(payload: dict, *, url: str | None = None, token: str | None = None,
                  timeout_s: float = 60.0, client: httpx.Client | None = None) -> dict:
    """POST the search to the REST API and return the MCP-compact shape. Raises RuntimeError with a SAFE message."""
    base = (url or bridge_url() or "").rstrip("/")
    if not base:
        raise RuntimeError("MG_MCP_BRIDGE_URL não definido")
    ensure_online("mcp-bridge", base)
    check_egress(base, "mcp-bridge")  # ANAM-005: allow-list (token e queries viajam para este host)
    post = client.post if client is not None else httpx.post
    try:
        r = post(f"{base}/memory/search", json=payload, headers=auth_headers(token), timeout=timeout_s)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"bridge REST indisponível: {type(exc).__name__}") from exc
    if r.status_code in (401, 403):
        raise RuntimeError(f"bridge REST recusou a credencial (HTTP {r.status_code}): defina MG_MCP_TOKEN")
    if r.status_code >= 400:
        raise RuntimeError(f"bridge REST HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as exc:
        raise RuntimeError("bridge REST devolveu JSON inválido") from exc
    m = data.get("metrics") or {}
    out = {"run_id": data.get("run_id"), "context": data.get("context", ""),
           "metrics": {k: m[k] for k in COMPACT_METRICS if m.get(k) is not None}}
    for k in ("mode_requested", "mode_used", "answer", "routing", "grounding", "attempts", "delegate", "pack_id"):
        if k in data:
            out[k] = data[k]
    return out
