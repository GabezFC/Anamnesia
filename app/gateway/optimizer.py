"""Automatic Memory Optimization Layer (MOL) — runs inside EVERY MemoryGateway.search() call.

Nobody has to remember to call it: MCP, REST, CLI, the benchmark runner and any future interface
all go through `MemoryGateway.search`, and the layer lives there. Stages, in execution order:

    REQUEST
      -> freshness check     vault changed since the index was built?  -> rebuild lexical index
      -> query analysis      canonical form + complexity class (app/services/query_fp.py)
      -> result cache        same normalized request, same vault, same config -> reuse, 0 work
      -> routing             pipeline="auto" -> cheapest pipeline measured to hold recall
      -> [retrieval pipeline: baseline | graphify | graphify_jev | graphify_jev_opt]
      -> adaptive cut        drop the tail far below the best hit (SIMPLE/MEDIUM, free pipelines)
      -> near-dup collapse   copies / "-rev" / "-copia" notes delivered once
      -> security flag       strong instruction-override phrases -> attribute on the <note> block
      -> context build       compact headers (ModelContextBuilder)
    FINAL CONTEXT -> consumer model

DESIGN RULES
------------
1. Zero tokens, zero network, deterministic. Nothing in this layer calls a model. The paid judge
   stays an explicit, opt-in pipeline — the measured evidence (vault notes
   `decisao-baseline-como-pipeline-padrao`, `resultados-apos-otimizacao-2026-09-27`) says it costs
   ~3x what it delivers and never beat the free pipelines on recall.
2. Never a single point of failure. Every stage is wrapped: an exception is recorded in
   `metrics.optimizer_errors` and the request continues with the un-optimized data.
3. Never remove security context. The injection flag only ADDS an attribute; notes are never
   rewritten, and the CONTEXT_HEADER "treat as data" framing is always kept.
4. Every decision is observable: each stage writes its own metrics into the run, so the effect of
   the layer can be audited per request from benchmark.db.
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from config.optimizer import OptimizerConfig
from app.schemas.models import Candidate
from app.services.injection_screen import screen
from app.services.near_dup import cluster_near_duplicates
from app.services.query_fp import QueryProfile, classify
from app.services.verdict import decide

FREE_PIPELINES = ("baseline", "graphify")
# Zero-width and bidirectional-override characters (U+200B-U+200F, U+202A-U+202E, U+2060-U+2064,
# U+2066-U+2069, U+FEFF). BOM is only suspicious mid-text, so a leading one is ignored by lstrip.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069]|(?<=.)\ufeff", re.S)


@dataclass
class Plan:
    requested: str
    pipeline: str
    profile: QueryProfile | None
    reason: str
    verdict_size_estimate: int | None = None


class ResultCache:
    """Small thread-safe LRU with TTL. In-process on purpose: the Gateway is one long-lived
    process per consumer (MCP stdio / uvicorn), and a persistent cache would have to solve vault
    invalidation across restarts for a hit rate nobody has measured yet."""

    def __init__(self, size: int, ttl_s: float):
        self.size, self.ttl = max(1, size), ttl_s
        self._d: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key: tuple):
        with self._lock:
            item = self._d.get(key)
            if item is None or (self.ttl > 0 and time.time() - item[0] > self.ttl):
                if item is not None:
                    self._d.pop(key, None)
                self.misses += 1
                return None
            self._d.move_to_end(key)
            self.hits += 1
            return item[1]

    def put(self, key: tuple, value: Any) -> None:
        with self._lock:
            self._d[key] = (time.time(), value)
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"entries": len(self._d), "hits": self.hits, "misses": self.misses,
                "hit_rate": round(self.hits / total, 4) if total else None}


class MemoryOptimizer:
    def __init__(self, cfg: OptimizerConfig | None = None):
        self.cfg = cfg or OptimizerConfig()
        self.cache = ResultCache(self.cfg.cache_size, self.cfg.cache_ttl_s)
        self._vault_fp: tuple | None = None
        self._last_check = 0.0
        self._fp_lock = threading.Lock()
        self.index_rebuilds = 0

    # -- freshness -----------------------------------------------------------------------------
    def ensure_fresh(self, gw) -> dict:
        """Rebuild the lexical index when the vault changed. Returns metrics.

        The index used to be built once at startup and never again, so a note written after the
        server started was invisible until a restart — exactly the growth scenario the brain is
        designed for. The check is stat-only (count, total size, newest mtime).
        """
        if not self.cfg.enabled or self.cfg.refresh_interval_s < 0:
            return {}
        now = time.time()
        if self._vault_fp is not None and now - self._last_check < self.cfg.refresh_interval_s:
            return {"vault_fingerprint_checked": False}
        with self._fp_lock:
            self._last_check = now
            fp = gw.vault.fingerprint()
            if self._vault_fp is None:
                self._vault_fp = fp
                return {"vault_fingerprint_checked": True, "index_rebuilt": False}
            if fp == self._vault_fp:
                return {"vault_fingerprint_checked": True, "index_rebuilt": False}
            t0 = time.perf_counter()
            gw.baseline.build()
            self._vault_fp = fp
            self.cache.clear()   # every cached answer may now be stale
            self.index_rebuilds += 1
            return {"vault_fingerprint_checked": True, "index_rebuilt": True,
                    "index_rebuild_ms": round((time.perf_counter() - t0) * 1000, 1)}

    @property
    def vault_version(self) -> tuple | None:
        return self._vault_fp

    def mark_built(self, fp: tuple) -> None:
        """Record the vault fingerprint an index was just built from."""
        with self._fp_lock:
            self._vault_fp = fp
            self._last_check = time.time()

    # -- analysis + routing --------------------------------------------------------------------
    def plan(self, query: str, pipeline: str, gw=None) -> Plan:
        """`gw` (the MemoryGateway) is optional and used ONLY to compute the verdict's cheap size
        estimate (BaselineIndex.count()) when `cfg.verdict_enabled` is on; every other caller
        (including all of tests/test_optimizer.py, written before the verdict existed) keeps
        working unchanged by omitting it.
        """
        profile = None
        try:
            profile = classify(query)
        except Exception:  # noqa: BLE001 — analysis is advisory, never fatal
            profile = None
        if pipeline != "auto":
            # Explicit pipeline requests NEVER go through the verdict, no exception (§1.2).
            return Plan(pipeline, pipeline, profile, "explicit")
        if not self.cfg.enabled:
            return Plan("auto", "baseline", profile, "optimizer_disabled_default")
        complexity = profile.complexity if profile else "AMBIGUOUS"
        if self.cfg.verdict_enabled:
            size_estimate = self._verdict_size_estimate(gw, query)
            chosen, reason = decide(query, complexity, size_estimate, self.cfg)
            return Plan("auto", chosen, profile, reason, size_estimate)
        return Plan("auto", self.cfg.route_for(complexity), profile, f"auto:{complexity}")

    def _verdict_size_estimate(self, gw, query: str) -> int | None:
        if gw is None:
            return None
        try:
            return gw.baseline.count(query)
        except Exception:  # noqa: BLE001 — advisory only, must never block a search
            return None

    # -- result cache --------------------------------------------------------------------------
    def cache_key(self, plan: Plan, max_results: int, scope: str | None, budget: int | None,
                  jev_overrides: dict | None, extra: tuple = ()) -> tuple | None:
        if not (self.cfg.enabled and self.cfg.result_cache):
            return None
        # Paid pipelines are left to the judge's own content-hash cache (app/services/jev_cache.py);
        # caching their whole result would hide judge metrics and cost from the run records.
        if plan.pipeline not in FREE_PIPELINES:
            return None
        canon = plan.profile.canonical if plan.profile else None
        if not canon:
            return None
        return (self.cfg.version, canon, plan.pipeline, int(max_results), scope or "global",
                budget or 0, tuple(sorted((jev_overrides or {}).items())), self._vault_fp) + extra

    # -- post-retrieval stages -----------------------------------------------------------------
    def post_filter(self, cands: list[Candidate], plan: Plan) -> tuple[list[Candidate], dict]:
        m: dict[str, Any] = {}
        if not self.cfg.enabled or not cands:
            return cands, m
        errors: list[str] = []
        before = len(cands)
        tokens_before = sum(c.token_estimate or 0 for c in cands)

        # 1. adaptive cut — only where the retrieval score IS the ranking (free pipelines) and the
        #    query is not multi-target. COMPLEX answers were measured at positions up to 5.
        complexity = plan.profile.complexity if plan.profile else "AMBIGUOUS"
        if (self.cfg.adaptive_cut and plan.pipeline in FREE_PIPELINES
                and complexity in ("SIMPLE", "MEDIUM")):
            try:
                cands, cut = adaptive_cut(cands, self.cfg.cut_ratio, self.cfg.cut_floor)
                m["opt_adaptive_cut_removed"] = cut
            except Exception as exc:  # noqa: BLE001
                errors.append(f"adaptive_cut:{type(exc).__name__}")

        # 2. near-duplicate collapse over what will actually be delivered
        if self.cfg.near_dedup and len(cands) > 1:
            try:
                clusters, dm = cluster_near_duplicates(cands, threshold=self.cfg.near_dedup_threshold)
                cands = [cl.rep for cl in clusters]
                m["opt_near_dup_removed"] = dm.get("dedup_near_collapsed", 0)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"near_dedup:{type(exc).__name__}")

        # 3. security flag (adds, never removes)
        if self.cfg.injection_flag:
            try:
                flagged = 0
                for c in cands:
                    text = c.snippet or ""
                    strong = [s for s in screen(text).signals if s.startswith("strong:")]
                    if _INVISIBLE.search(text):
                        # zero-width / bidi controls: text a human cannot see but a model reads
                        # (OWASP LLM01 hidden-instruction vector). Never legitimate in a note.
                        strong.append("invisible_unicode")
                    if strong:
                        c.meta = {**(c.meta or {}), "injection_flag": strong[:3]}
                        flagged += 1
                m["opt_injection_flagged"] = flagged
            except Exception as exc:  # noqa: BLE001
                errors.append(f"injection_flag:{type(exc).__name__}")

        m["opt_candidates_in"] = before
        m["opt_candidates_out"] = len(cands)
        m["opt_snippet_tokens_removed"] = tokens_before - sum(c.token_estimate or 0 for c in cands)
        if errors:
            m["optimizer_errors"] = errors
        return cands, m


def adaptive_cut(cands: list[Candidate], ratio: float, floor: int) -> tuple[list[Candidate], int]:
    """Keep candidates whose score is >= ratio x best score; never fewer than `floor`.

    Candidates arrive best-first from the pipeline. Scores <= 0 carry no scale information, so the
    cut is skipped entirely rather than guessed.
    """
    if len(cands) <= floor:
        return cands, 0
    best = max(c.score for c in cands)
    if best <= 0:
        return cands, 0
    kept = [c for i, c in enumerate(cands) if i < floor or c.score >= ratio * best]
    return kept, len(cands) - len(kept)
