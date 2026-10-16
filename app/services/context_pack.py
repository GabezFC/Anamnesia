"""Context Pack (ANA-147) + per-block explanation (ANA-149) + multi-signal quality report (ANA-152).

A ContextPack is the CONTRACT of one retrieval, not a service: a small JSON record of what was
delivered (path, sha256 of the note text at that moment, mtime, historical/injection flags, why),
under which budget and policy versions. It does not store the note text. A sub-agent that receives
`pack_id` can ask whether the sources still match (`verify`) before trusting the context.

Zero tokens, zero network. Packs live in `<data>/data/context_packs/<id>.json` (atomic write, ttl).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

# ANAM-020: prefixo estável + sufixo dinâmico, memória como DADO, snapshot de sessão congelado.
from app.services.context_prompt import (  # noqa: F401 - re-exportado como API pública do pack
    CachePrompt, build_cache_aware_prompt, freeze_snapshot, place_lost_in_middle, prefix_fingerprint,
    retrieved_from_result, snapshot_drift, wrap_memory)

PACK_VERSION = 1
DEFAULT_TTL_S = 24 * 3600
_ID_RE = re.compile(r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------------------------------------
# ANA-149: why this block
# ---------------------------------------------------------------------------------------------
def explain_candidate(c) -> str:
    """One short, non-empty line: retrieval channel, score, JEV verdict, routing flags. Never empty."""
    meta = getattr(c, "meta", None) or {}
    origin = (getattr(c, "origin", "") or "").strip() or "retrieval"
    parts = [f"canal={origin}", f"score={float(getattr(c, 'score', 0.0) or 0.0):.3f}"]
    rel = getattr(c, "relevance", None)
    if rel is not None:
        parts.append(f"relevância={float(rel):.2f}")
    dec = getattr(c, "decision", None)
    if dec:
        parts.append(f"decisão={dec}")
    if meta.get("historical"):
        parts.append("histórico")
    if meta.get("temporal_demoted"):
        parts.append("rebaixada(temporal)")
    if meta.get("expired"):
        parts.append("expirada")
    if meta.get("conflict"):
        parts.append("conflito")
    if meta.get("injection_flag"):
        parts.append("flag:injeção")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------
# ANA-147: the pack
# ---------------------------------------------------------------------------------------------
def packs_dir() -> Path:
    from config.paths import user_data_dir
    return user_data_dir() / "data" / "context_packs"


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def build_pack(gateway, result, *, scope: str | None = None, token_budget: int | None = None,
               ttl_s: int = DEFAULT_TTL_S, policy: dict | None = None, snapshot: dict | None = None,
               freeze: list[dict] | None = None, session_id: str | None = None) -> dict:
    """Build (not save) the pack for a MemoryResult. `sources[*].sha256` = sha256 of the note text now.

    ANAM-020: `freeze=[{path,text}]` (+`session_id`) congela o hotset num snapshot imutável; `snapshot=`
    reutiliza um já congelado. O pack registra `snapshot_id`, `prefix_sha256` e `cache_breakpoint_index`
    (índice do último bloco estável em `build_cache_aware_prompt`); o conteúdo do snapshot NÃO entra no
    pack (continua sem guardar texto de nota)."""
    if snapshot is None and freeze is not None:
        snapshot = freeze_snapshot(freeze, session_id=session_id or "")
    vault = gateway.vault
    by_file = {}
    for c in getattr(result, "candidates", None) or []:
        by_file.setdefault(c.source_file, c)
    sources, ctx_tokens = [], int(getattr(result, "metrics", {}).get("context_tokens") or 0)
    for s in result.sources:
        c = by_file.get(s.file)
        meta = (getattr(c, "meta", None) or {}) if c is not None else {}
        try:
            text = vault.read(s.file)
            digest = _sha(text)
        except Exception:  # noqa: BLE001 - a source that vanished is reported, not fatal
            digest = None
        try:
            mtime = round(os.stat(vault._abs(s.file)).st_mtime, 3)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            mtime = None
        sources.append({"path": s.file, "section": s.section, "sha256": digest, "mtime": mtime,
                        "historical": bool(meta.get("historical")), "injection_flag": bool(meta.get("injection_flag")),
                        "tokens": s.tokens, "why": s.why or (explain_candidate(c) if c is not None else "")})
    budget = int(token_budget or getattr(getattr(gateway, "bench_cfg", None), "context_budget", 0) or 0) or None
    pack = {
        "pack_version": PACK_VERSION, "id": uuid.uuid4().hex[:12], "run_id": result.run_id, "query": result.query,
        "scope": scope, "pipeline": result.pipeline, "sources": sources,
        "token_budget": budget, "context_tokens": ctx_tokens,
        "policy": policy or {"optimizer": getattr(gateway.optimizer.cfg, "provenance_mode", None)},
        "created_at": time.time(), "ttl_s": int(ttl_s),
    }
    if snapshot is not None:
        pack.update({"snapshot_id": snapshot["id"], "prefix_sha256": snapshot["prefix_sha256"],
                     "cache_breakpoint_index": 1 if snapshot["hot_text"] else 0,
                     "snapshot_hotset": sorted(snapshot["hotset_sha"])})
    return pack


def save_pack(pack: dict) -> str:
    d = packs_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pack-", suffix=".part", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(pack, fh, ensure_ascii=False, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, d / f"{pack['id']}.json")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return pack["id"]


def load_pack(pack_id: str) -> dict | None:
    if not isinstance(pack_id, str) or not _ID_RE.match(pack_id):
        raise ValueError("pack_id inválido")
    p = packs_dir() / f"{pack_id}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def is_expired(pack: dict, now: float | None = None) -> bool:
    return (now or time.time()) > pack["created_at"] + pack.get("ttl_s", DEFAULT_TTL_S)


def verify_pack(gateway, pack: dict) -> dict:
    """Re-hash every source now. {ok, expired, changed:[path], missing:[path], within_budget}."""
    changed, missing = [], []
    for s in pack["sources"]:
        try:
            now = _sha(gateway.vault.read(s["path"]))
        except Exception:  # noqa: BLE001
            missing.append(s["path"])
            continue
        if s.get("sha256") != now:
            changed.append(s["path"])
    budget = pack.get("token_budget")
    within = budget is None or pack.get("context_tokens", 0) <= budget
    exp = is_expired(pack)
    return {"ok": not changed and not missing and within and not exp, "expired": exp, "changed": changed,
            "missing": missing, "within_budget": within}


def reap_packs(now: float | None = None) -> int:
    n = 0
    d = packs_dir()
    if d.is_dir():
        for p in d.glob("*.json"):
            try:
                if is_expired(json.loads(p.read_text(encoding="utf-8")), now):
                    p.unlink()
                    n += 1
            except (OSError, ValueError, KeyError):
                continue
    return n


# ---------------------------------------------------------------------------------------------
# ANA-152: six side-by-side signals, NO composite score
# ---------------------------------------------------------------------------------------------
def quality_signals(gateway, result, labels: dict[str, str] | None = None) -> dict:
    """The six measured signals of one delivered context, reported side by side.

    relevance  -> share of delivered sources labelled `relevant` (None while there are no labels)
    redundancy -> max pairwise sequence similarity between delivered snippets (near_dup measure)
    freshness  -> share of delivered sources that are historical/expired
    injection  -> count of delivered blocks flagged by the screen
    tokens     -> delivered context tokens
    sources    -> number of distinct source files
    `composite` is intentionally None until >=100 human-labelled items exist (ANA-152 gate).
    """
    from app.services.near_dup import similarity
    cands = [c for c in (getattr(result, "candidates", None) or [])
             if any(s.file == c.source_file for s in result.sources)]
    red = 0.0
    for i, a in enumerate(cands):
        for b in cands[i + 1:]:
            if a.source_file != b.source_file:
                red = max(red, similarity(a.snippet, b.snippet))
    metas = [(c.meta or {}) for c in cands]
    n = len(result.sources) or 1
    stale = sum(1 for m in metas if m.get("historical") or m.get("expired"))
    rel = None
    if labels:
        rel = round(sum(1 for s in result.sources if labels.get(s.file) == "relevant") / n, 4)
    return {"relevance": rel, "redundancy": round(red, 4), "freshness_stale_share": round(stale / n, 4),
            "injection_flags": sum(1 for m in metas if m.get("injection_flag")),
            "tokens": int(result.metrics.get("context_tokens") or 0),
            "sources": len({s.file for s in result.sources}),
            "composite": None, "composite_blocked_by": "ANA-011/ANA-109: needs >=100 labelled items"}
