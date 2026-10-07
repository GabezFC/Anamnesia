"""Connections API (Fase 9). Offline by default; secret values are never returned or logged."""
from __future__ import annotations

import os
import shutil
import urllib.request

from fastapi import APIRouter, Body, Depends, HTTPException

from app.connections import secrets as secret_store
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
    keys = {k: {"has_key": secret_store.has_key(k), "masked": secret_store.masked(k)} for k in c.env_keys}
    out["detected"] = detect(c)
    out["has_key"] = bool(keys) and all(v["has_key"] for v in keys.values())
    out["masked"] = next((v["masked"] for v in keys.values() if v["masked"]), None)
    out["keys"] = keys
    return out


def _check_env_key(c: Connection, payload: dict) -> str:
    env_key = payload.get("env_key") if isinstance(payload, dict) else None
    if not isinstance(env_key, str) or env_key not in c.env_keys:
        raise HTTPException(400, f"env_key inválida para {c.id}; permitidas: {list(c.env_keys)}")
    return env_key


@router.get("")
def list_connections() -> dict:
    return {"connections": [_view(c) for c in _catalog()]}


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


def _ollama_probe() -> tuple[bool, str]:
    host = os.environ.get("OLLAMA_HOST") or "http://localhost:11434"
    if not host.startswith("http"):
        host = "http://" + host
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as r:  # noqa: S310
            return r.status == 200, f"HTTP {r.status}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


@router.post("/{cid}/test", dependencies=[Depends(require_local_write)])
def test_connection(cid: str) -> dict:
    c = _get(cid)
    checks = []
    if c.command:
        found = shutil.which(c.command.split()[0]) is not None
        checks.append({"name": "command_on_path", "ok": found or c.type == "mcp"})
    for k in c.env_keys:
        checks.append({"name": f"env:{k}", "ok": secret_store.has_key(k)})
    snip = build_snippet(c)
    checks.append({"name": "mcp_snippet", "ok": snip["status"] == "ok", "status": snip["status"]})
    network_checked = False
    note = "teste estrutural offline; nenhuma chamada de rede feita"
    if os.environ.get("ANAMNESIA_ALLOW_NETWORK_TEST") == "1":
        if c.id == "ollama":
            ok, detail = _ollama_probe()
            checks.append({"name": "network:ollama", "ok": ok, "detail": detail})
            network_checked = True
            note = "sonda de rede apenas para Ollama local"
        else:
            note = "teste de rede ainda não implementado para esta conexão; apenas verificação estrutural"
    structural = [x for x in checks if x["name"] != "mcp_snippet"]
    return {"id": c.id, "ok": all(x["ok"] for x in structural), "detected": detect(c), "checks": checks,
            "network_checked": network_checked, "note": note}
