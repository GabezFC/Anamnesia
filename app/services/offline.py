"""ANA-224: guaranteed OFFLINE mode.

`ANAMNESIA_OFFLINE=1` (alias: `OFFLINE=1`) turns the process into a no-external-network process:

  * `ensure_online(what)` is the CENTRAL, explicit guard: every provider adapter calls it before building a
    request (see `app/adapters/models/errors.ensure_paid_allowed` / `providers.py`) and gets a clear
    `OfflineBlocked` instead of a socket error.
  * `install_if_enabled()` is the safety net for code that never calls the guard (httpx, urllib, the
    anthropic/openai SDKs, TypeSafe, DNS): it wraps `socket.socket.connect/connect_ex/sendto/...` and
    `socket.getaddrinfo` so ANY non-loopback destination raises `OfflineBlocked` BEFORE a socket is opened to it.

Loopback (127.0.0.0/8, ::1, localhost, unix sockets) stays allowed: local Ollama/vLLM, the REST API and tests that
talk to a fake server on 127.0.0.1 are not "the network".

Not covered (honest limit): child processes (agent CLIs such as `claude`/`codex`) run in their own interpreter and
are NOT constrained by this in-process guard; the launchers only refuse to start them when OFFLINE is on
(`ensure_online("agent:<name>")`).
"""
from __future__ import annotations

import ipaddress
import os
import socket
import threading
from collections.abc import Mapping
from typing import Any

_TRUE = {"1", "true", "yes", "on"}
ENV_VARS = ("ANAMNESIA_OFFLINE", "OFFLINE")


class OfflineBlocked(ConnectionError):
    """An outbound connection/lookup was refused because OFFLINE mode is on."""


def offline_enabled(env: Mapping | None = None) -> bool:
    e = os.environ if env is None else env
    return any(str(e.get(k, "")).strip().lower() in _TRUE for k in ENV_VARS)


def is_loopback_host(host: object) -> bool:
    if host is None or isinstance(host, (bytes, bytearray)):
        return True  # unix path / bytes / wildcard: not an external destination
    if not isinstance(host, str) or not host:
        return True
    h = host.strip("[]").split("%")[0].lower()
    if h in {"localhost", "localhost.localdomain", "ip6-localhost", "0.0.0.0", "::"}:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def is_loopback_url(url: str) -> bool:
    from urllib.parse import urlsplit
    return is_loopback_host(urlsplit(url).hostname)


def ensure_online(what: str, url: str | None = None) -> None:
    """Raise `OfflineBlocked` when OFFLINE is on and `what` would leave the machine.

    A loopback `url` is allowed (local model servers); no `url` means 'remote by nature' (paid provider, agent CLI).
    """
    if not offline_enabled():
        return
    if url is not None and is_loopback_url(url):
        return
    raise OfflineBlocked(f"OFFLINE=1: chamada de rede bloqueada ({what})")


# --------------------------------------------------------------------------- socket-level safety net
_lock = threading.Lock()
_originals: dict[str, Any] = {}


def _check(address: object, what: str) -> None:
    if isinstance(address, tuple) and address and not is_loopback_host(address[0]):
        raise OfflineBlocked(f"OFFLINE=1: {what} para {address[0]!r} bloqueado")


def installed() -> bool:
    return bool(_originals)


def install() -> None:
    """Wrap the socket layer (idempotent)."""
    with _lock:
        if _originals:
            return
        _originals.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                          sendto=socket.socket.sendto, getaddrinfo=socket.getaddrinfo)
        real = dict(_originals)

        def connect(self, address):  # noqa: ANN001
            _check(address, "conexão")
            return real["connect"](self, address)

        def connect_ex(self, address):  # noqa: ANN001
            _check(address, "conexão")
            return real["connect_ex"](self, address)

        def sendto(self, data, *args):  # noqa: ANN001
            if args:
                _check(args[-1], "datagrama")
            return real["sendto"](self, data, *args)

        def getaddrinfo(host, *a, **kw):  # noqa: ANN001
            if not is_loopback_host(host):
                raise OfflineBlocked(f"OFFLINE=1: resolução DNS de {host!r} bloqueada")
            return real["getaddrinfo"](host, *a, **kw)

        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.socket.sendto = sendto  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]


def uninstall() -> None:
    with _lock:
        if not _originals:
            return
        socket.socket.connect = _originals["connect"]  # type: ignore[method-assign]
        socket.socket.connect_ex = _originals["connect_ex"]  # type: ignore[method-assign]
        socket.socket.sendto = _originals["sendto"]  # type: ignore[method-assign]
        socket.getaddrinfo = _originals["getaddrinfo"]  # type: ignore[assignment]
        _originals.clear()


def install_if_enabled() -> bool:
    """Entry points (REST app, MCP server, CLI) call this once at startup. Returns True when OFFLINE is active."""
    if offline_enabled():
        install()
        return True
    return False
