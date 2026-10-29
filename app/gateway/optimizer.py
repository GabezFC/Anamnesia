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
      -> temporality         archived / superseded notes demoted, history only when it is asked for
      -> consistency         conflicting notes: newest kept, older demoted and marked
      -> provenance          one compact `[fonte: ...]` line per delivered source
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
   rewritten, and the CONTEXT_HEADER "treat as data" framing is always kept. The provenance line adds
   metadata about the note, never authority: a note does not become more trustworthy by being
   stored, and the line never repeats the header's instruction to the consumer.
4. Never change the frozen pipeline. `graphify_jev` is the benchmark reference point, so the
   memory-metadata stages skip it entirely and its delivered context stays byte-identical.
5. Every decision is observable: each stage writes its own metrics into the run, so the effect of
   the layer can be audited per request from benchmark.db.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from config.optimizer import OptimizerConfig
from app.gateway.vault_manifest import (diff_manifests, entry_is_affected, fold, is_small, read_touched,
                                        reindex_incremental, scan_manifest)
from app.schemas.models import Candidate
from app.services.injection_screen import screen
from app.services.near_dup import cluster_near_duplicates
from app.services.provenance import (ProvenanceIndex, apply_temporal, provenance_tokens,
                                     resolve_conflicts, wants_history)
from app.services.query_fp import QueryProfile, classify
from app.services.verdict import decide

FREE_PIPELINES = ("baseline", "graphify")
# The frozen reference pipeline (§1.3): it is the benchmark's comparison point, so the memory
# metadata stages (provenance, temporality, conflict demotion) never touch it. Every other pipeline
# -- baseline, graphify and the optimized cascade -- gets them.
FROZEN_PIPELINES = ("graphify_jev",)
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


def hotset_enabled() -> bool:
    """ANAM-037: MG_HOTSET flag (see Cerebro IA (Anamnesia/Migracao-docs-repo-2026-10-24/bench/anam-036-037.md) for the default and why)."""
    return os.environ.get("MG_HOTSET", HOTSET_DEFAULT).strip().lower() in ("1", "true", "yes", "on")


HOTSET_DEFAULT = "0"


class HotSet:
    """ANAM-037: hit counter with exponential decay, per canonical query and per note.

    score(t) = value * 0.5 ** ((t - last) / half_life_s): a thing hit 10 times a week ago weighs less
    than one hit twice a minute ago. In-process, bounded (`max_items`), thread-safe, zero I/O.
    Used for (a) protecting hot cache entries from LRU eviction and (b) pre-warming the top-N
    queries/notes after a vault change wipes the result cache. Clock is injectable for tests.
    """

    def __init__(self, half_life_s: float = 3600.0, top_n: int = 16, max_items: int = 2048, clock=time.time):
        self.half_life_s = max(1.0, float(half_life_s))
        self.top_n, self.max_items, self._clock = max(1, int(top_n)), max(8, int(max_items)), clock
        self._q: dict[str, list] = {}      # canonical -> [value, last_ts, replay_args]
        self._n: dict[str, list] = {}      # note file -> [value, last_ts]
        self._lock = threading.Lock()

    def _decayed(self, value: float, last: float, now: float) -> float:
        return value * math.pow(0.5, max(0.0, now - last) / self.half_life_s)

    def _bump(self, d: dict, key: str, now: float, extra=None) -> None:
        cur = d.get(key)
        val = (self._decayed(cur[0], cur[1], now) if cur else 0.0) + 1.0
        keep = [extra] if extra is not None else (cur[2:] if cur else [])
        d[key] = [val, now] + keep
        if len(d) > self.max_items:   # drop the coldest 10%
            cold = sorted(d, key=lambda k: self._decayed(d[k][0], d[k][1], now))[: max(1, len(d) // 10)]
            for k in cold:
                d.pop(k, None)

    def touch_query(self, canonical: str, replay: tuple | None = None) -> None:
        with self._lock:
            self._bump(self._q, canonical, self._clock(), replay)

    def touch_notes(self, files) -> None:
        now = self._clock()
        with self._lock:
            for f in set(files):
                self._bump(self._n, f, now)

    def query_score(self, canonical: str) -> float:
        with self._lock:
            cur = self._q.get(canonical)
            return self._decayed(cur[0], cur[1], self._clock()) if cur else 0.0

    def top_queries(self, n: int | None = None) -> list[tuple[str, float, tuple | None]]:
        now = self._clock()
        with self._lock:
            rows = [(k, self._decayed(v[0], v[1], now), v[2] if len(v) > 2 else None) for k, v in self._q.items()]
        rows.sort(key=lambda r: -r[1])
        return rows[: n or self.top_n]

    def top_notes(self, n: int | None = None) -> list[tuple[str, float]]:
        now = self._clock()
        with self._lock:
            rows = [(k, self._decayed(v[0], v[1], now)) for k, v in self._n.items()]
        rows.sort(key=lambda r: -r[1])
        return rows[: n or self.top_n]


class ResultCache:
    """Small thread-safe LRU with TTL. In-process on purpose: the Gateway is one long-lived
    process per consumer (MCP stdio / uvicorn), and a persistent cache would have to solve vault
    invalidation across restarts for a hit rate nobody has measured yet."""

    def __init__(self, size: int, ttl_s: float):
        self.size, self.ttl = max(1, size), ttl_s
        self._d: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = 0
        self.stale_evictions = 0
        self.selective_evictions = 0
        self.score_fn = None   # ANAM-037: key -> hotness; None = plain LRU
        self.protected_evictions = 0

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
                if self.score_fn is None:
                    self._d.popitem(last=False)
                    continue
                # ANAM-037: among the 4 least-recently-used entries evict the coldest (ties -> oldest)
                tail = list(self._d)[:4]
                victim = min(tail, key=lambda k: self.score_fn(k))
                self.protected_evictions += victim != tail[0]
                self._d.pop(victim, None)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def invalidate_where(self, pred) -> tuple[int, int]:
        """ANAM-018: drop only the entries for which `pred(key, value)` is True -> (dropped, kept)."""
        with self._lock:
            doomed = [k for k, (_, v) in self._d.items() if pred(k, v)]
            for k in doomed:
                self._d.pop(k, None)
            self.selective_evictions += len(doomed)
            return len(doomed), len(self._d)

    def invalidate(self, key: tuple) -> None:
        """Drop one entry found stale on a hit; the earlier hit is reclassified as a miss."""
        with self._lock:
            if self._d.pop(key, None) is not None:
                self.hits = max(0, self.hits - 1)
                self.misses += 1
                self.stale_evictions += 1

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {"entries": len(self._d), "hits": self.hits, "misses": self.misses,
                "stale_evictions": self.stale_evictions,
                "selective_evictions": self.selective_evictions,
                "hit_rate": round(self.hits / total, 4) if total else None}


def _experiments_digest(gw) -> dict | None:
    from app.retrieval.experiments import get_flags
    exp = get_flags(gw)
    return exp.digest() if exp.active() else None


class MemoryOptimizer:
    def __init__(self, cfg: OptimizerConfig | None = None):
        self.cfg = cfg or OptimizerConfig()
        self.cache = ResultCache(self.cfg.cache_size, self.cfg.cache_ttl_s)
        self._vault_fp: tuple | None = None
        self._manifest: dict | None = None   # ANAM-018: {rel: (mtime_ns, size)} the index was built from
        self._cache_epoch = 0                # bumped only when the cache is wiped wholesale
        self._last_check = 0.0
        self._fp_lock = threading.Lock()
        self.index_rebuilds = 0
        self._prov: ProvenanceIndex | None = None
        self._prov_fp: tuple | None = None
        # ANAM-037: decaying hit counters (flag MG_HOTSET); None = feature off, zero overhead.
        self.hotset: HotSet | None = None
        self._prewarming = threading.local()
        self.prewarmed = 0
        if hotset_enabled():
            self.enable_hotset()

    def enable_hotset(self, hotset: "HotSet | None" = None) -> HotSet:
        self.hotset = hotset or HotSet(float(os.environ.get("MG_HOTSET_HALFLIFE_S", "3600") or 3600),
                                       int(os.environ.get("MG_HOTSET_TOPN", "16") or 16))
        self.cache.score_fn = lambda key: self.hotset.query_score(key[1]) if len(key) > 1 else 0.0
        return self.hotset

    def prewarm(self, gw) -> dict:
        """ANAM-037: re-run the top-N hot queries (cache misses only) and touch the top-N hot notes so
        their bytes sit in the OS page cache for the guard re-hash. Never raises."""
        hs = self.hotset
        if hs is None or getattr(self._prewarming, "on", False):
            return {}
        self._prewarming.on = True
        done = read = 0
        try:
            for _canon, _score, replay in hs.top_queries():
                if replay is None:
                    continue
                try:
                    gw.search(replay[0], replay[1], replay[2], persist=False)
                    done += 1
                except Exception:  # noqa: BLE001 -- warming is best effort
                    pass
            for f, _s in hs.top_notes():
                try:
                    gw.vault.read(f)
                    read += 1
                except Exception:  # noqa: BLE001
                    pass
        finally:
            self._prewarming.on = False
        self.prewarmed += done
        return {"hotset_prewarm_queries": done, "hotset_prewarm_notes": read}

    # -- provenance index --------------------------------------------------------------------------
    def provenance_index(self, gw) -> ProvenanceIndex | None:
        """Frontmatter cache for the files this request delivers, rebuilt whenever the vault changes.

        Reuses the fingerprint the freshness check already computed (`ensure_fresh` runs on every
        search and is throttled by `refresh_interval_s`), so this costs no extra stat pass per
        request -- measured: a separate stat-only fingerprint on the 520-note corpus cost ~30 ms per
        search, more than the retrieval it annotated. Outside a search (unit tests calling
        `post_filter` with no fingerprint yet) it is computed once and cached. Returns None when
        there is no gateway: the metadata stages then have nothing to read and are skipped, exactly
        as they were before this stage existed.
        """
        if gw is None:
            return None
        with self._fp_lock:
            fp = self._vault_fp
            if fp is None:
                try:
                    fp = gw.vault.fingerprint()
                except Exception:  # noqa: BLE001 — advisory stage, never fatal
                    return None
            if self._prov is None or self._prov_fp != fp:
                self._prov = ProvenanceIndex(gw.vault)
                self._prov_fp = fp
            return self._prov

    # -- freshness -----------------------------------------------------------------------------
    def ensure_fresh(self, gw) -> dict:
        """Rebuild the lexical index when the vault changed. Returns metrics.

        The index used to be built once at startup and never again, so a note written after the
        server started was invisible until a restart — exactly the growth scenario the brain is
        designed for. The check is stat-only (count, total size, newest mtime).
        """
        if self.cfg.refresh_interval_s < 0:
            return {}
        now = time.time()
        if self._vault_fp is not None and now - self._last_check < self.cfg.refresh_interval_s:
            return {"vault_fingerprint_checked": False}
        with self._fp_lock:
            self._last_check = now
            man = scan_manifest(gw.vault)           # ANAM-018: one scandir pass, no per-file stat
            fp = man.fp if man is not None else gw.vault.fingerprint()
            if self._vault_fp is None:
                self._vault_fp, self._manifest = fp, (man.files if man else None)
                return {"vault_fingerprint_checked": True, "index_rebuilt": False}
            files_changed = (man is not None and self._manifest is not None
                             and man.files != self._manifest)
            if fp == self._vault_fp and not files_changed:
                if self._manifest is None and man is not None:
                    self._manifest = man.files
                return {"vault_fingerprint_checked": True, "index_rebuilt": False}
            t0 = time.perf_counter()
            m = self._apply_change(gw, man)
            # Aggregate fingerprints can collide even when individual files changed.
            self._prov = None
            self._prov_fp = None
            self._vault_fp, self._manifest = fp, (man.files if man else None)
            self.index_rebuilds += 1
            m.update({"vault_fingerprint_checked": True, "index_rebuilt": True,
                      "index_rebuild_ms": round((time.perf_counter() - t0) * 1000, 1)})
        if self.hotset is not None and not getattr(self._prewarming, "on", False):
            m.update(self.prewarm(gw))   # outside _fp_lock; re-entrant searches see a settled fingerprint
        return m

    def _apply_change(self, gw, man) -> dict:
        """ANAM-018: per-file reindex + selective cache invalidation when the diff is small and
        provable; otherwise the original full rebuild + full cache clear (the safe path)."""
        old = self._manifest
        if man is not None and old is not None:
            diff = diff_manifests(old, man.files)
            if is_small(diff, len(man.files)):
                texts = read_touched(gw.vault, diff.touched)
                if texts is not None and reindex_incremental(gw.baseline, diff, texts, len(man.files)):
                    folded = {r: fold(t) for r, t in texts.items()}
                    dropped, kept = self.cache.invalidate_where(
                        lambda k, v: entry_is_affected(k, v, diff, folded))
                    return {"index_incremental": True, "index_files_touched": diff.size(),
                            "cache_dropped": dropped, "cache_kept": kept}
        gw.baseline.build()
        self.cache.clear()   # every cached answer may now be stale
        self._cache_epoch += 1
        return {"index_incremental": False}

    @property
    def vault_version(self) -> tuple | None:
        return self._vault_fp

    def mark_built(self, fp: tuple, manifest: dict | None = None) -> None:
        """Record the vault fingerprint an index was just built from (and, when known, its manifest)."""
        with self._fp_lock:
            self._vault_fp = fp
            self._manifest = manifest
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
        if self.hotset is not None and not getattr(self._prewarming, "on", False):
            replay = ((plan.profile.raw, plan.requested, int(max_results))
                      if (scope or "global") == "global" and not jev_overrides and not budget else None)
            self.hotset.touch_query(canon, replay)
        return (self.cfg.version, canon, plan.pipeline, int(max_results), scope or "global",
                budget or 0, tuple(sorted((jev_overrides or {}).items())), self._cache_epoch) + extra

    # -- ANA-021: effective-configuration digest ------------------------------------------------
    def config_digest(self, gw, plan: Plan) -> str:
        """Digest of everything that changes WHAT a search returns but is not in the cache key's
        explicit fields: resolved optional stages (env + local_settings.json), retrieval knobs,
        JEV config, optimizer flags and the graph.json identity (mtime_ns+size). Flipping any of them
        yields a different key, so a stale answer can never be served after a settings change."""
        import hashlib
        import json
        from dataclasses import asdict, is_dataclass

        def _d(o):
            if o is None:
                return None
            return asdict(o) if is_dataclass(o) else dict(getattr(o, "__dict__", {}))

        try:
            st = gw.graphify.graph_path.stat()
            graph_id = [st.st_mtime_ns, st.st_size]
        except (OSError, AttributeError):
            graph_id = None
        rc = gw.retrieval_cfg
        doc = {
            "stages": _d(gw.optional_stages_cfg.resolved(plan.pipeline)),
            "retrieval": {k: getattr(rc, k, None) for k in (
                "max_candidates", "snippet_max_tokens", "dedup_max_per_note", "model_context_budget",
                "per_source_max_tokens", "prefilter_top_k", "prefilter_lexical_weight", "jev_min_survivors",
                "graphify_bin", "graphify_hybrid", "graphify_text_seeds", "graphify_graph_expand",
                "graphify_query_budget", "graphify_timeout_s", "graphify_stale_fallback_s",
                "ppr_enabled", "ppr_alpha", "ppr_iters", "ppr_top_n")},
            "jev": _d(gw.jev_cfg),
            "optimizer": _d(self.cfg),
            "opt": _d(getattr(gw, "opt_cfg", None)),
            "graph": graph_id,
            "experiments": _experiments_digest(gw),   # Onda 9: flipping a flag must change the key
        }
        raw = json.dumps(doc, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    # -- ANA-025: anti-poisoning of the result cache ----------------------------------------------
    @staticmethod
    def cacheable(metrics: dict, cands) -> tuple[bool, str]:
        """A result that carries an error, an optimizer error or an injection flag is never stored."""
        if metrics.get("error"):
            return False, "error"
        for k, v in metrics.items():
            if (k == "optimizer_errors" or k.endswith("_errors")) and v:
                return False, k
        if metrics.get("opt_injection_flagged"):
            return False, "injection_flag"
        if any((c.meta or {}).get("injection_flag") for c in cands):
            return False, "injection_flag"
        return True, ""

    def source_guard(self, gw, sources) -> dict | None:
        """Content hashes of the files actually delivered + the vault fingerprint at store time."""
        import hashlib
        files: dict[str, str] = {}
        try:
            for s in sources:
                if s.file not in files:
                    files[s.file] = hashlib.sha1(gw.vault.read(s.file).encode("utf-8")).hexdigest()
        except Exception:  # noqa: BLE001 -- cannot prove freshness -> do not cache
            return None
        return {"files": files, "vault_fp": self._vault_fp}

    def guard_valid(self, gw, guard: dict | None) -> bool:
        """Re-hash the delivered files on a hit (a few small reads). Any edit/removal -> invalid."""
        import hashlib
        if not guard:
            return False
        try:
            for f, h in guard["files"].items():
                if hashlib.sha1(gw.vault.read(f).encode("utf-8")).hexdigest() != h:
                    return False
        except Exception:  # noqa: BLE001
            return False
        return True

    # -- post-retrieval stages -----------------------------------------------------------------
    def post_filter(self, cands: list[Candidate], plan: Plan, gw=None,
                    query: str | None = None) -> tuple[list[Candidate], dict]:
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

        if self.hotset is not None and not getattr(self._prewarming, "on", False):
            self.hotset.touch_notes(c.source_file for c in cands if getattr(c, "source_file", None))
        m["opt_candidates_in"] = before
        m["opt_candidates_out"] = len(cands)
        m["opt_snippet_tokens_removed"] = tokens_before - sum(c.token_estimate or 0 for c in cands)

        # 4. memory metadata: temporality (supersession / archived) and conflict demotion. Both read
        #    the note's own frontmatter through the provenance index and only ever DEMOTE or MARK.
        #    The frozen pipeline is skipped (design rule 4) and so is a request with no gateway.
        if plan.pipeline not in FROZEN_PIPELINES:
            index = self.provenance_index(gw)
            raw_query = query if query is not None else (plan.profile.raw if plan.profile else "")
            if self.cfg.temporal_demote:
                try:
                    cands, tm = apply_temporal(cands, index, wants_history(raw_query),
                                               self.cfg.historical_demote,
                                               exclude=self.cfg.historical_exclude)
                    m.update(tm)
                    m["opt_candidates_out"] = len(cands)
                    m["opt_snippet_tokens_removed"] = tokens_before - sum(
                        c.token_estimate or 0 for c in cands)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"temporal:{type(exc).__name__}")
            if self.cfg.conflict_check:
                try:
                    cands, cm = resolve_conflicts(cands, index, self.cfg.conflict_demote,
                                                  self.cfg.conflict_overlap)
                    m.update(cm)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"conflicts:{type(exc).__name__}")

        if errors:
            m["optimizer_errors"] = errors
        return cands, m

    def provenance_lines(self, cands: list[Candidate], gw) -> tuple[dict[str, str], dict]:
        """`{candidate_id: "[fonte: ...]"}` for the delivered candidates, plus its cost in tokens.

        The line is built from the note's own frontmatter (file name, type, status, last update,
        project) and nothing else; a note with no frontmatter still gets a line, with `?` where the
        note declares nothing. The historical marker is appended for archived/superseded notes, so
        history is visible in the delivered text instead of only in the metrics. Returns {} for the
        frozen pipeline and for a disabled layer.
        """
        out: dict[str, str] = {}
        if not self.cfg.enabled or not self.cfg.provenance or not cands:
            return out, {}
        index = self.provenance_index(gw)
        if index is None:
            return out, {}
        compact = getattr(self.cfg, "provenance_mode", "full") == "compact"  # ANA-161
        for n, c in enumerate(cands, 1):
            line = index.compact_line(c.source_file, n) if compact else index.line(c.source_file)
            if (c.meta or {}).get("historical") or (c.meta or {}).get("expired"):
                line = f"{line} {index.marker(c.source_file)}".strip()
            if line:
                out[c.candidate_id] = line
        return out, {"provenance_tokens": provenance_tokens(list(out.values())),
                     "provenance_lines": len(out),
                     # Proof that the provenance line integrates with the injection flag instead of
                     # repeating it: these lines sit on blocks that already carry the warning attr.
                     "provenance_on_flagged": sum(1 for c in cands
                                                  if c.candidate_id in out
                                                  and (c.meta or {}).get("injection_flag"))}


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
