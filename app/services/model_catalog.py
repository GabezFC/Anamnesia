"""Catalogo de modelos locais com proveniencia/licenca (ANAM-031).

Le ``config/model_catalog.json`` (so campos verificados). O modo ``comercial``
bloqueia modelos sem licenca verificada ou com uso comercial negado/nao
declarado. Pesos nunca vao ao Git (``data/local_ai/models/`` no .gitignore).
"""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "config", "model_catalog.json")

REQUIRED_FIELDS = ("id", "repo", "revision_sha", "license", "license_status", "commercial_use",
                   "params_b", "size_gb", "context_tokens", "min_vram_gb", "min_ram_gb",
                   "source_urls", "verified_fields")
_NC_MARKERS = ("non-commercial", "noncommercial", "-nc", "research-only", "research only")


class CatalogError(ValueError):
    pass


class CommercialBlocked(CatalogError):
    pass


def validate_catalog(cat: dict) -> list:
    """Devolve lista de erros de esquema (vazia = ok)."""
    errs = []
    if not isinstance(cat, dict) or not isinstance(cat.get("models"), list):
        return ["raiz deve ter 'models' (lista)"]
    seen = set()
    for i, m in enumerate(cat["models"]):
        mid = m.get("id") if isinstance(m, dict) else None
        if not mid:
            errs.append(f"models[{i}]: sem id")
            continue
        if mid in seen:
            errs.append(f"{mid}: id duplicado")
        seen.add(mid)
        for f in REQUIRED_FIELDS:
            if f not in m:
                errs.append(f"{mid}: campo ausente '{f}'")
        if m.get("license_status") not in ("VERIFIED", "UNVERIFIED"):
            errs.append(f"{mid}: license_status invalido")
        if m.get("license_status") == "VERIFIED" and (not m.get("license")
                                                      or not isinstance(m.get("commercial_use"), bool)):
            errs.append(f"{mid}: VERIFIED exige license e commercial_use booleano")
        if m.get("license_status") == "UNVERIFIED" and (m.get("license") or m.get("commercial_use") is not None):
            errs.append(f"{mid}: UNVERIFIED nao pode carregar license/commercial_use")
        sha = m.get("revision_sha")
        if sha is not None and not (isinstance(sha, str) and len(sha) == 40
                                    and all(c in "0123456789abcdef" for c in sha)):
            errs.append(f"{mid}: revision_sha deve ser SHA-1 de 40 hex ou null")
    return errs


def load_catalog(path: Optional[str] = None) -> dict:
    with open(path or DEFAULT_PATH, encoding="utf-8") as f:
        cat = json.load(f)
    errs = validate_catalog(cat)
    if errs:
        raise CatalogError("; ".join(errs))
    return cat


def is_commercial_ok(entry: dict) -> bool:
    lic = str(entry.get("license") or "").lower()
    return (entry.get("license_status") == "VERIFIED" and entry.get("commercial_use") is True
            and not any(t in lic for t in _NC_MARKERS))


def list_models(mode: str = "comercial", path: Optional[str] = None) -> list:
    """``mode='comercial'`` filtra; qualquer outro modo devolve tudo."""
    models = load_catalog(path)["models"]
    return [m for m in models if is_commercial_ok(m)] if mode == "comercial" else list(models)


def get_model(model_id: str, mode: str = "comercial", path: Optional[str] = None) -> dict:
    for m in load_catalog(path)["models"]:
        if m["id"] == model_id:
            if mode == "comercial" and not is_commercial_ok(m):
                raise CommercialBlocked(
                    f"{model_id}: licenca {m.get('license_status')} / uso comercial "
                    f"{m.get('commercial_use')} - bloqueado no modo comercial")
            return m
    raise KeyError(model_id)
