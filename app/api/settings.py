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


@router.get("")
def get_settings(db: Database = Depends(get_db)) -> dict:
    return store.load_settings(db).model_dump()


@router.put("", dependencies=[Depends(require_local_write)])
def put_settings(body: store.SettingsPatch, db: Database = Depends(get_db)) -> dict:
    """Only the fields present in the body change. `budget` merges key by key; the other dict
    fields (subagent_preset, prefilter_cache, terminal_layout) are replaced whole."""
    return store.save_patch(db, body).model_dump()
