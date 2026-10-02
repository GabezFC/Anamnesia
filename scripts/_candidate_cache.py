"""On-disk cache of candidate generation for the diagnostic scripts (§5.5 sweeps).

`scripts/check_jev_snippet.py` and `scripts/sweep_prefilter.py` both call
`_graphify_candidates(gw, question, allow_ppr=False)` — BM25 over the whole vault plus graph
expansion — for the same questions on every invocation, and that stage is deterministic: it only
changes when the vault or the graph changes. Re-running a check therefore paid for the same
retrieval again. This module caches the first element of the result (`uniq`, the deduplicated
candidates, which is all both scripts use — the metrics dict they discard is NOT cached) as one
pickle per (vault fingerprint, question).

Invalidation: `vault_fingerprint()` hashes the (relative path, mtime_ns, size) of every `.md`
under the vault plus the mtime of `graphify-out/graph.json`. Editing, adding or removing one note,
or rebuilding the graph, changes the fingerprint and therefore every key — a stale candidate list
cannot outlive the state that produced it. The graph mtime is in the fingerprint because the
mirror is shared across vaults and `_ensure_fresh_graph` exists precisely because a stale graph is
read silently. `--no-cache` in either script bypasses all of it.

A cache is an optimization, never a correctness input: a corrupt or unreadable pickle is treated
as a miss and recomputed, so this can only ever cost time, never return the wrong answer silently.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: Pickles live under the project's ignored `data/` tree — derived from a private vault, never
#: published (see .gitignore), and disposable by construction.
CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "candidates"

#: Folders that hold no retrievable note and would only slow the walk / add noise to the key.
SKIP_DIRS = frozenset({".obsidian", ".trash", ".git", "graphify-out", "__pycache__"})

GRAPH_REL = "graphify-out/graph.json"

#: Bump when the pickled shape changes, so old entries are recomputed instead of misread.
CACHE_VERSION = 1


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _markdown_files(vault: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(vault):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        out.extend(Path(dirpath) / name for name in sorted(filenames) if name.endswith(".md"))
    return sorted(out)


def vault_fingerprint(vault: Path | str) -> str:
    """Cheap state of the vault's retrievable content: (path, mtime_ns, size) per `.md`, plus the
    graph's mtime. Metadata only — hashing every note's bytes would cost more than the retrieval
    this cache exists to avoid, while mtime+size still changes on any real edit."""
    vault = Path(vault)
    h = hashlib.sha1()
    for p in _markdown_files(vault):
        try:
            st = p.stat()
        except OSError:
            continue  # removed between walk and stat
        h.update(f"{p.relative_to(vault).as_posix()}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
    h.update(f"graph\0{_mtime_ns(vault / GRAPH_REL)}\n".encode())
    return h.hexdigest()


def cache_key(vault: Path | str, question: str, fingerprint: str | None = None) -> str:
    """sha1 of the vault fingerprint + the question: one key per state/question pair."""
    fp = fingerprint if fingerprint is not None else vault_fingerprint(vault)
    return hashlib.sha1(f"{fp}\0{question}".encode()).hexdigest()


def cache_path(vault: Path | str, question: str) -> Path:
    return CACHE_DIR / f"{cache_key(vault, question)}.pkl"


def _compute(gw, question: str):
    """The real thing, imported at call time so a caller (or a test) can replace it."""
    from app.retrieval.pipelines import _graphify_candidates
    uniq, _metrics = _graphify_candidates(gw, question, allow_ppr=False)
    return uniq


def _read(path: Path, fingerprint: str, question: str):
    """Pickled candidates, or None on a miss / anything unexpected in the file."""
    try:
        payload = pickle.loads(path.read_bytes())
    except (OSError, ValueError, EOFError, pickle.UnpicklingError, AttributeError, ImportError,
            IndexError, KeyError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("version") != CACHE_VERSION:
        return None
    if payload.get("fingerprint") != fingerprint or payload.get("question") != question:
        return None
    candidates = payload.get("candidates")
    return candidates if isinstance(candidates, list) else None


def _store(path: Path, fingerprint: str, question: str, candidates: list) -> None:
    payload = {"version": CACHE_VERSION, "fingerprint": fingerprint, "question": question,
               "candidates": candidates}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Write beside the target and rename: a reader never sees a half-written pickle, and a crash
    # leaves the previous entry intact instead of a corrupt one.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
    os.replace(tmp, path)


def cached_candidates(gw, vault: Path | str, question: str, *, use_cache: bool = True) -> list:
    """`uniq` for `question`, from disk when the vault is unchanged since it was computed.

    `use_cache=False` computes and returns without reading or writing the cache.
    """
    if not use_cache:
        return _compute(gw, question)
    fingerprint = vault_fingerprint(vault)
    path = CACHE_DIR / f"{cache_key(vault, question, fingerprint)}.pkl"
    hit = _read(path, fingerprint, question)
    if hit is not None:
        return hit
    uniq = _compute(gw, question)
    _store(path, fingerprint, question, uniq)
    return uniq
