"""GET/PUT /api/settings — app settings persisted server-side (SQLite `kv`). PUT is a partial merge."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.database.db import Database
from app.services import settings_store as store
from app.services.security import require_local_write

router = APIRouter(prefix="/api/settings")


def get_db() -> Database:
    """Default: the running gateway's database. Tests override this dependency."""
    from app.api import routes
    return routes.gw().db


def _view(s: store.Settings) -> dict:
    """Resposta da API. `terminal_layout` é espelho DEPRECADO de `workspace_layout` (X04), mantido por ≥1 versão."""
    d = s.model_dump()
    d["terminal_layout"] = d["workspace_layout"]
    return d


@router.get("")
def get_settings(db: Database = Depends(get_db)) -> dict:
    return _view(store.load_settings(db))


@router.put("", dependencies=[Depends(require_local_write)])
def put_settings(body: store.SettingsPatch, db: Database = Depends(get_db)) -> dict:
    """Only the fields present in the body change. `budget` merges key by key; the other dict
    fields (subagent_preset, prefilter_cache, workspace_layout) are replaced whole.
    `terminal_layout` (nome antigo) ainda é aceito como alias de `workspace_layout`."""
    return _view(store.save_patch(db, body))
