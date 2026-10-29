"""FASE 9: regressões do CLI achadas na auditoria real (stats --session com string)."""
from __future__ import annotations

from app.benchmark.report import render_session
from app.database.db import Database


def test_render_session_filters_by_session_id_not_offset(tmp_path):
    # Antes: db.list_runs(100000, session_id) passava a sessão como OFFSET -> sqlite3.IntegrityError
    db = Database(tmp_path / "b.db")
    out = render_session(db, "sessao-inexistente")
    assert "sem runs" in out
