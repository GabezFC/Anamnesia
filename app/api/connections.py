"""Connections API (Fase 9). Offline by default; secret values are never returned or logged."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from app.connections import secrets as secret_store
from app.connections import verify
from app.connections.catalog import CatalogError, Connection, detect, load_catalog
from app.connections.snippets import build_snippet
from app.services.security import require_local_write

router = APIRouter(prefix="/api/connections")


def _catalog() -> list[Connection]:
    try:
        return load_catalog()
    except CatalogError as e:
        raise HTTPException(500, f"catálogo de conexões inválido: {e}") from e


def _get(cid: str) -> Connection:
    c = next((c for c in _catalog() if c.id == cid), None)
    if c is None:
        raise HTTPException(404, f"conexão desconhecida: {cid}")
    return c


def _view(c: Connection) -> dict:
    out = c.public()
    keys = {k: {"has_key": secret_store.has_key(k), "masked": secret_store.masked(k)} for k in c.key_names}
    out["detected"] = detect(c)
    out["has_key"] = bool(keys) and all(v["has_key"] for v in keys.values())
    out["masked"] = next((v["masked"] for v in keys.values() if v["masked"]), None)
    out["keys"] = keys
    out["uses_providers"] = _uses_providers(c)
    out.update(verify.state_of(c))
    return out


def _uses_providers(c: Connection) -> list[str]:
    """Agente x provedor x credencial: ids dos cartões de provedor cuja credencial o agente consome.
    O agente não tem campo de chave próprio; a chave mora uma única vez no cartão do provedor."""
    if c.type != "agent":
        return []
    from app.connections.agents import load_agents
    spec = next((a for a in load_agents() if a.id == c.id), None)
    wanted = set(spec.env_keys) if spec else set()
    return [m.id for m in _catalog() if m.type == "model" and wanted & set(m.env_keys)]


def _check_env_key(c: Connection, payload: dict) -> str:
    env_key = payload.get("env_key") if isinstance(payload, dict) else None
    if not isinstance(env_key, str) or env_key not in c.key_names:
        raise HTTPException(400, f"env_key inválida para {c.id}; permitidas: {list(c.key_names)}")
    return env_key


@router.get("")
def list_connections() -> dict:
    out: dict = {"connections": [_view(c) for c in _catalog()]}
    try:                                    # ANA-187/190: additive, only when a resilience flag is on
        from app.routing import circuit_breaker as _cb, health as _hl
        if _cb.breaker_enabled() or _hl.health_enabled():
            out["resilience"] = _hl.health_report()
    except Exception:  # noqa: BLE001 -- never break the listing
        pass
    return out


@router.get("/resilience/state")
def resilience_state() -> dict:
    """Read-only: circuit-breaker state + real-call health per model (no secrets, no prompts)."""
    from app.routing import health as _hl
    return _hl.health_report()


@router.put("/{cid}/secret", dependencies=[Depends(require_local_write)])
def put_secret(cid: str, payload: dict = Body(...)) -> dict:
    c = _get(cid)
    env_key = _check_env_key(c, payload)
    try:
        secret_store.set_key(env_key, payload.get("value"))
    except secret_store.SecretError as e:
        raise HTTPException(400, str(e)) from None
    return {"id": c.id, "env_key": env_key, "has_key": True, "masked": secret_store.masked(env_key)}


@router.delete("/{cid}/secret", dependencies=[Depends(require_local_write)])
def delete_secret(cid: str, payload: dict = Body(...)) -> dict:
    c = _get(cid)
    env_key = _check_env_key(c, payload)
    removed = secret_store.delete_key(env_key)
    return {"id": c.id, "env_key": env_key, "removed": removed, "has_key": secret_store.has_key(env_key)}


@router.get("/{cid}/snippet")
def get_snippet(cid: str) -> dict:
    c = _get(cid)
    return {"id": c.id, **build_snippet(c)}


@router.post("/{cid}/test", dependencies=[Depends(require_local_write)])
def test_connection(cid: str) -> dict:
    """Verificação real por provedor (ver app/connections/verify.py). Nunca devolve 'connected' sem prova."""
    return verify.run_test(_get(cid))
