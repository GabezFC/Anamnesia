# ANAM-007 — lock multiprocesso no memory_store

Experimento (`docs/bench/anam007_bench.py`): N processos (spawn), cada um com seu próprio `SavedContextStore`
no MESMO diretório, dão 80 feedbacks `useful` no total na mesma nota (Windows 11, Python 3.14).

| Cenário | Antes (RLock por instância) | Depois (FileLock + replace com retry) |
|---|---|---|
| 2 procs × 40 | contador 40/80, jsonl 78, 2 exceções (PermissionError/WinError 5) | contador 80/80, jsonl 80, 0 exceções (1,14 s) |
| 4 procs × 20 | contador 20/80, jsonl 51, 29 exceções (PermissionError/WinError 5) | contador 80/80, jsonl 80, 0 exceções (1,34 s) |

Implementação: `app/memory_store/filelock.py` (msvcrt.locking / fcntl.flock sobre `<root>_state/.store.lock`,
reentrante, timeout 30 s via `MG_STORE_LOCK_TIMEOUT_S`) e `replace_with_retry` (PermissionError, backoff 5→100 ms,
12 tentativas) usado em `_replace` e `to_trash`. `store._lock` mantém a interface de context manager, então
`lifecycle.feedback` (leitura-modificação-escrita + append no jsonl) fica serializado entre processos sem alteração.
Testes: `tests/test_anam007_lock.py`.
