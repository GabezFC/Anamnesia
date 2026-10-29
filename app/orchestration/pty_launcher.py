"""Acesso ao gerenciador PTY INTERNO (launcher não visual).

O `TerminalManager` (app/terminals) é infraestrutura do launcher de orquestração
(`ANAMNESIA_DELEGATE_LAUNCHER=terminal`). Não há rota REST/WS nem UI de terminal. Este módulo é o dono do
singleton; nenhuma rota de projeto depende dele.

- `get_manager()`: cria sob demanda (só o modo `terminal` do delegate chama).
- `peek_manager()`: devolve o singleton SE já existir, senão `None` — nunca instancia (usado para encerrar
  sessões de um projeto desvinculado sem criar um PTY à toa).
- `close_project_sessions(project_id)`: fecha sessões do projeto no manager existente; no-op sem manager.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_manager = None


def get_manager():
    """Gerenciador de sessões PTY (singleton, criação preguiçosa). Uso interno do backend."""
    global _manager
    with _lock:
        if _manager is None:
            from app.terminals.manager import TerminalManager
            _manager = TerminalManager()
        return _manager


def peek_manager():
    """Singleton existente ou None. NUNCA instancia o manager."""
    with _lock:
        return _manager


def close_project_sessions(project_id: str, reason: str = "project_removed") -> int:
    """Fecha as sessões PTY do projeto se o manager já existir; sem manager devolve 0. Nunca levanta."""
    mgr = peek_manager()
    if mgr is None:
        return 0
    closed = 0
    try:
        for s in list(mgr.list()):
            if getattr(s, "project_id", None) == project_id:
                mgr.close(s.id, reason)
                closed += 1
    except Exception:  # noqa: BLE001 - desvincular o cadastro não pode falhar por causa de sessão
        pass
    return closed


def reset_for_tests() -> None:
    global _manager
    with _lock:
        _manager = None
