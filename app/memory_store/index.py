"""Make saved notes searchable by the existing retrieval baseline, without touching the user's vault.

The saved-context folder is mounted on the gateway's `ObsidianVault` as an extra READ-ONLY root
under the virtual prefix `saved_context/` (see `ObsidianVault.add_extra_root`). BM25/FTS, the
freshness fingerprint and the graphify mirror then see the notes as ordinary markdown files, while:

  * the vault root is never written, and `vault.hash_all()` (the "vault unchanged" proof) still
    covers ONLY the user's own notes;
  * with an empty/missing folder nothing is listed, so listings, fingerprint and search results
    are identical to a gateway that never called `attach_saved_context`.

New notes are picked up by the optimizer's periodic fingerprint check (`MG_VAULT_REFRESH_S`);
`reindex()` forces it right away (e.g. after an API save).
"""
from __future__ import annotations

from pathlib import Path

from config.paths import saved_context_dir

PREFIX = "saved_context"


def attach_saved_context(target, root: Path | str | None = None):
    """Mount the saved-context folder on a MemoryGateway (or a bare ObsidianVault). Idempotent."""
    vault = getattr(target, "vault", target)
    vault.add_extra_root(PREFIX, root if root is not None else saved_context_dir())
    return target


def reindex(gateway) -> None:
    """Rebuild the lexical index now so a just-saved note is searchable on the next query."""
    gateway.baseline.build()
    try:
        gateway.optimizer.mark_built(gateway.vault.fingerprint())
        gateway.optimizer.cache.clear()
    except Exception:  # noqa: BLE001 - freshness bookkeeping is advisory
        pass
