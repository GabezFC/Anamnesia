"""FastAPI dependencies (ANA-106). Override in tests with `app.dependency_overrides[get_gateway]`."""
from __future__ import annotations

from fastapi import HTTPException

from app.core.state import STATE, GatewayNotReady


def get_gateway():
    try:
        return STATE.require_gateway()
    except GatewayNotReady as exc:
        raise HTTPException(503, "gateway não inicializado") from exc
