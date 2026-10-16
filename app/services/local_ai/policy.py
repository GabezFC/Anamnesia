"""Politica de privacidade/licenca para modelos locais (reusa ``model_catalog``; ANAM-031)."""
from __future__ import annotations

import os
from typing import Optional

from app.services import model_catalog as mc

MODE_ENV = "MG_LOCAL_AI_MODE"   # "comercial" (default, mais restritivo) | qualquer outro = pessoal/pesquisa


class ModelBlocked(PermissionError):
    pass


def current_mode(mode: Optional[str] = None) -> str:
    return (mode or os.environ.get(MODE_ENV) or "comercial").strip().lower()


def ensure_model_allowed(model_id: str, mode: Optional[str] = None, catalog_path: Optional[str] = None,
                         aliases: Optional[dict] = None) -> dict:
    """Devolve a entrada do catalogo ou levanta ``ModelBlocked``.

    Modo comercial: modelo fora do catalogo, UNVERIFIED, sem uso comercial ou non-commercial => bloqueado.
    Outros modos: modelo fora do catalogo passa com ``catalog=None`` (o chamador deve rotular como nao verificado).
    ``aliases`` mapeia nome do runtime (ex. tag Ollama) -> id do catalogo.
    """
    m = current_mode(mode)
    cid = (aliases or {}).get(model_id, model_id)
    try:
        return {"catalog": mc.get_model(cid, mode=m, path=catalog_path), "mode": m, "catalog_id": cid}
    except mc.CommercialBlocked as exc:
        raise ModelBlocked(str(exc)) from exc
    except KeyError:
        if m == "comercial":
            raise ModelBlocked(f"{model_id}: fora do catalogo (licenca UNVERIFIED) - bloqueado no modo comercial") from None
        return {"catalog": None, "mode": m, "catalog_id": None}
