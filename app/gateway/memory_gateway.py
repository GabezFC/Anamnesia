"""MemoryGateway — central orchestration service (§31). Agent- and model-agnostic.

search()        retrieval + filtering + context building for one pipeline
retrieve()      raw candidates of a pipeline (no filtering)
filter()        JEV judgment over given candidates
build_context() ModelContextBuilder over candidates
benchmark()     delegated to app.benchmark.runner
metrics()       aggregate statistics from SQLite
"""
from __future__ import annotations

import atexit
import contextvars
import json
import queue
import threading
import time
import os
import uuid
import weakref
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from config.benchmark import BenchmarkConfig
from config.jev import JevConfig
from config.optimization import OptimizationConfig, OptionalStagesConfig
from config.optimizer import OptimizerConfig
from config.retrieval import RetrievalConfig
from app.core.request_context import install_log_trace, request_scope, run_scope, trace_metrics
from app.database.db import Database
from app.gateway.budget_guard import BudgetGuard
from app.gateway.context_builder import ModelContextBuilder
from app.gateway.optimizer import MemoryOptimizer
from app.retrieval.experiments import get_flags
from app.retrieval.incremental_index import make_baseline_index
from app.retrieval.graphify_hybrid import GraphIndex
from app.retrieval.optional_stages import apply_optional_stages
from app.retrieval.pipelines import PIPELINE_FUNCS
from app.schemas.models import JEV_PIPELINES, PIPELINES, MemoryResult
from app.services.graphify import GraphifyService
from app.services.jev import JevService
from app.services.metrics import get_logger, jsonl
from app.services.obsidian import ObsidianVault
from app.services.pricing import cost_usd
from app.services.scope import Scope, discover, parse_scope

# Bumped whenever a change alters the MEANING of a metric already in metrics_json -- e.g. the PT
# calibration factor in app/core/tokens.py:estimate_tokens (§5.5 item 9). Lets a consumer
# (the history line chart, item 2.1) split series instead of plotting two incompatible measurement
# scales as one continuous line. Runs recorded before this field existed simply lack the key.
METRICS_VERSION = 1

# `active_scope` used to be plain instance state (`self.active_scope = ...`), which is a race: a
# single MemoryGateway instance is shared across every request (app/api/routes.py `_state["gateway"]`),
# and FastAPI runs sync endpoints in a thread pool, so two concurrent searches with different scopes
# could interleave their set/read/reset and leak one request's project scope into another's results
# (§5.4 da proposta 2026-09-28, item 8 de pendencias-e-riscos-abertos). A ContextVar is per-context
# (per-thread when a thread never copies another's context, per-Task under asyncio), so each request's
# value is isolated even though every request shares this one gateway object and this one variable.
_active_scope_var: contextvars.ContextVar["Scope | None"] = contextvars.ContextVar(
    "mg_active_scope", default=None)


def _env_on(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class _BenchLog:
    """ANAM-019: append of the benchmark jsonl line off the request path (one writer thread, ordered)."""

    def __init__(self, log) -> None:
        self._q: queue.Queue = queue.Queue()
        self._log = log
        self._t = threading.Thread(target=self._loop, name="anamnesia-benchlog", daemon=True)
        self._t.start()

    def put(self, record: dict) -> None:
        self._q.put(record)

    def _loop(self) -> None:
        while True:
            rec = self._q.get()
            try:
                if rec is None:
                    return
                jsonl("benchmark", rec)
            except Exception as exc:  # noqa: BLE001 - a failed log line never kills the writer
                self._log.warning("benchmark.jsonl async write failed: %s", type(exc).__name__)
            finally:
                self._q.task_done()

    def flush(self, timeout: float = 10.0) -> bool:
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.001)
        return not self._q.unfinished_tasks

    def stop(self) -> None:
        self._q.put(None)
        self._t.join(timeout=5)


def _flush_at_exit(ref: "weakref.ref[MemoryGateway]") -> None:
    gw = ref()
    if gw is not None:
        gw.flush_persistence()


class MemoryGateway:
    def __init__(self, retrieval_cfg: RetrievalConfig | None = None, jev_cfg: JevConfig | None = None,
                 bench_cfg: BenchmarkConfig | None = None, db: Database | None = None,
                 jev_backend=None, graphify_service: GraphifyService | None = None,
                 opt_cfg: OptimizationConfig | None = None, optimizer_cfg: OptimizerConfig | None = None,
                 optional_stages_cfg: OptionalStagesConfig | None = None,
                 async_persist: bool | None = None):
        self.retrieval_cfg = retrieval_cfg or RetrievalConfig()
        self.jev_cfg = jev_cfg or JevConfig()
        self.bench_cfg = bench_cfg or BenchmarkConfig()
        # Token optimizations (§32) for the `graphify_jev_opt` cascade only — every other pipeline
        # ignores this. Default is `default_cascade()` (§1.3): an interface that never configures
        # this explicitly still gets the calibrated cascade, not a silent no-op. The frozen
        # `OptimizationConfig.baseline()` reference stays reachable by passing it explicitly (e.g.
        # a benchmark arm), and `graphify_jev` (not this pipeline) remains the frozen comparison
        # point regardless of what this default is.
        self.opt_cfg = opt_cfg or OptimizationConfig.default_cascade()
        # Optional retrieval stages (§1.4/§5.5) — off by default, resolved against
        # config/local_settings.json on every search() so a frontend toggle needs no restart.
        # Applies to every pipeline except graphify_jev (frozen). See app/retrieval/optional_stages.py.
        self.optional_stages_cfg = optional_stages_cfg or OptionalStagesConfig()
        # Automatic Memory Optimization Layer: runs inside EVERY search() (app/gateway/optimizer.py).
        self.optimizer = MemoryOptimizer(optimizer_cfg or OptimizerConfig())
        self.budget_guard = BudgetGuard()  # T6.4, inert unless ANAMNESIA_BUDGET_ENFORCE=1
        # Cache isolation handle. "" in production; a benchmark sets it so its arms cannot read
        # judgements cached by a previous run (see app/services/jev.py cache_key).
        self.cache_namespace = ""
        self.log = get_logger()
        self.vault = ObsidianVault(self.retrieval_cfg.vault_path, self.retrieval_cfg.excluded_dirs)
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault não encontrado: {self.vault.root}")
        # ANAM-019: write-behind persistence (db writer thread + jsonl thread), flushed on close()/atexit and
        # before any read (Database.query flushes). Opt-in: entry points that serve requests (REST lifespan, MCP
        # server) pass async_persist=True; library/test/CLI use stays synchronous unless
        # ANAMNESIA_GATEWAY_ASYNC_PERSIST=1. ANAMNESIA_GATEWAY_ASYNC_PERSIST=0 forces sync everywhere.
        env = os.environ.get("ANAMNESIA_GATEWAY_ASYNC_PERSIST", "").strip().lower()
        self._async_persist = False if env in ("0", "false", "no", "off") else (
            bool(async_persist) or env in ("1", "true", "yes", "on"))
        self.db = db or Database(self.bench_cfg.db_path, compress_context=self.bench_cfg.db_compress_context,
                                 async_writes=True if self._async_persist else None)
        self._persist_max_queue = int(os.environ.get("ANAMNESIA_PERSIST_MAX_QUEUE", "1000") or 1000)
        self._bench_log = _BenchLog(self.log) if self._async_persist else None
        self._atexit_cb = atexit.register(_flush_at_exit, weakref.ref(self))
        install_log_trace(self.log)           # ANAM-012: "[trace=<id>]" prefix in application.log
        db_path = Path(self.db.path).resolve()
        if self.vault.root in db_path.parents:
            raise PermissionError("benchmark.db não pode ficar dentro do vault (§58)")
        # ANA-102: incremental FTS5 index only with MG_INCREMENTAL_INDEX=1 (default OFF); the index file
        # lives next to the benchmark db, never inside the (read-only) vault.
        self.baseline = make_baseline_index(self.vault, db_path.parent / "baseline_fts.db")
        self.graphify = graphify_service or GraphifyService(
            self.vault, self.retrieval_cfg.mirror_dir, self.retrieval_cfg.graphify_bin,
            self.retrieval_cfg.graphify_query_budget, self.retrieval_cfg.graphify_timeout_s,
            stale_fallback_s=self.retrieval_cfg.graphify_stale_fallback_s)
        self._jev_backend = jev_backend
        self.jev = self.make_jev(self.jev_cfg)
        # Lazy in-memory view of graph.json used by the hybrid retriever (reloads on mtime change).
        self.graph_index = GraphIndex(self.graphify.graph_path)

    # -- scope (contextvar-backed, §5.4) -------------------------------------------
    def _saved_note_project(self, rel_path: str) -> str | None:
        """F9-01: `projeto:` frontmatter of an agent-saved note (`saved_context/...`), else None.

        Path-only scoping hid every saved note from `projeto:X` searches: its path carries no project.
        Only extra-root files (the Gateway's own folder) are resolved -- user-vault notes keep the
        path-only rule -- and the read is read-only and bounded to the frontmatter head. Cached per file
        by (mtime_ns, size), so a save/update/delete is seen on the next search with no explicit
        invalidation. Called only while filtering a NON-global scope: unscoped searches pay nothing.
        """
        vault = self.vault
        if not vault.extra_roots or vault._extra_split(rel_path) is None:
            return None
        try:
            p = vault._abs(rel_path)
            st = p.stat()
        except Exception:  # noqa: BLE001 -- missing/escaping path: no project, fail closed
            return None
        cache = self.__dict__.setdefault("_saved_project_cache", {})
        key = (st.st_mtime_ns, st.st_size)
        hit = cache.get(rel_path)
        if hit is not None and hit[0] == key:
            return hit[1]
        project = None
        try:
            from app.services.obsidian import frontmatter_fields
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.read(8192)
            value = frontmatter_fields(head).get("projeto")
            project = value.strip() if isinstance(value, str) and value.strip() else None
        except Exception:  # noqa: BLE001
            project = None
        if len(cache) > 20000:
            cache.clear()
        cache[rel_path] = (key, project)
        return project

    @property
    def active_scope(self) -> "Scope | None":
        """Set per-search so pipelines can scope candidates early; None means global (§14).

        Backed by a module-level ContextVar (not instance state) so concurrent searches on this
        SAME shared gateway instance never see each other's scope, even though they all read and
        write through `gw.active_scope`.
        """
        return _active_scope_var.get()

    @active_scope.setter
    def active_scope(self, value: "Scope | None") -> None:
        _active_scope_var.set(value)

    # -- projects -----------------------------------------------------------------
    def projects(self) -> dict:
        """Discover project/area entities from the vault (§15, §30). Fully generic: a new project
        folder is picked up with no code change. Counts are read from the filesystem, not cached.
        """
        from app.services.scope import areas as area_counts

        paths = self.vault.list_markdown()
        registry = discover(paths)
        return {
            "total_notes": len(paths),
            "areas": area_counts(paths),
            "projects": [p.to_dict() for p in sorted(registry.values(), key=lambda x: -x.note_count)],
        }

    # -- helpers ------------------------------------------------------------------
    def make_jev(self, cfg: JevConfig, cache: bool | None = None) -> JevService:
        use_cache = self.bench_cfg.cache_enabled if cache is None else cache
        return JevService(cfg, backend=self._jev_backend,
                          cache_get=self.db.cache_get if use_cache else None,
                          cache_put=self.db.cache_put if use_cache else None,
                          logger=lambda e: jsonl("jev", e),
                          cache_namespace=self.cache_namespace)

    def warm(self) -> dict:
        t0 = time.perf_counter()
        self.baseline.build()
        # Graphify is OPTIONAL for serving: the default route (auto -> baseline) needs only the
        # lexical index. A missing binary or a failed `graphify update` used to raise here and take
        # the whole MCP server down with it — a single point of failure for a stage that is not on
        # the default path. Now it is recorded and the graph pipelines degrade (hybrid falls back
        # to the last graph.json, or to BM25 seeds only).
        try:
            g = self.graphify.build()
        except Exception as exc:  # noqa: BLE001
            self.log.warning("graphify build failed, continuing without it: %s", exc)
            g = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        try:  # anchor the freshness check to the index we just built
            self.optimizer.mark_built(self.vault.fingerprint())
        except Exception:  # noqa: BLE001
            pass
        self.graphify_warm = g  # ANA-017: the benchmark runner reads this to refuse degraded graphify arms
        return {"baseline_sections": self.baseline.sections_indexed, "graphify": g,
                "warm_ms": round((time.perf_counter() - t0) * 1000, 1)}

    # -- public API ---------------------------------------------------------------
    def retrieve(self, query: str, pipeline: str = "graphify"):
        if pipeline == "baseline":
            return self.baseline.search(query, self.retrieval_cfg.max_candidates)
        return self.graphify.search(query, self.retrieval_cfg.max_candidates)[0]

    def filter(self, query: str, candidates, jev_overrides: dict | None = None):
        jev = self.make_jev(replace(self.jev_cfg, **(jev_overrides or {}))) if jev_overrides else self.jev
        return jev.evaluate(query, candidates)

    def build_context(self, candidates, full_texts=None, budget: int | None = None, provenance=None,
                      mark_unjudged: bool = False, nonce: bool = False, fit_query: str | None = None):
        oc = self.optimizer.cfg
        b = ModelContextBuilder(budget or self.retrieval_cfg.model_context_budget,
                                self.retrieval_cfg.per_source_max_tokens,
                                compact_headers=oc.enabled and oc.compact_headers,
                                section_max_chars=oc.header_section_max_chars,
                                screen_delivered=oc.enabled and oc.injection_flag,
                                mark_unjudged=mark_unjudged, nonce=nonce, fit_query=fit_query)
        out = b.build(candidates, full_texts, provenance=provenance)
        self.last_budget_stats = {"blocks_dropped_budget": b.blocks_dropped_budget,
                                  "blocks_fitted_budget": b.blocks_fitted_budget}
        return out

    def provenance_for(self, cands, pipeline: str):
        """Provenance lines for the delivered candidates — {} for the frozen reference pipeline.

        `pipeline` must be the EFFECTIVE one (`plan.pipeline`), not what the caller asked for:
        `graphify_jev` is a legal routing target, so an `auto` request can land on the frozen
        pipeline and must be left byte-identical too. Every other pipeline gets the lines when the
        layer is on.
        """
        from app.gateway.optimizer import FROZEN_PIPELINES
        if pipeline in FROZEN_PIPELINES:
            return {}, {}
        try:
            return self.optimizer.provenance_lines(cands, self)
        except Exception as exc:  # noqa: BLE001 — metadata only, never break a search
            self.log.warning("provenance failed: %s", exc)
            return {}, {"provenance_errors": [type(exc).__name__]}

    def search(self, query: str, pipeline: str = "auto", max_results: int = 10,
               jev_overrides: dict[str, Any] | None = None, context_budget: int | None = None,
               persist: bool = True, run_meta: dict[str, Any] | None = None,
               scope: str | None = None) -> MemoryResult:
        """Public entry. ANAM-012: opens (or joins) the request scope so one trace_id covers the whole search."""
        meta = dict(run_meta or {})
        meta["run_id"] = meta.get("run_id") or uuid.uuid4().hex[:12]
        with request_scope(), run_scope(meta["run_id"]):
            return self._search_impl(query, pipeline, max_results, jev_overrides, context_budget,
                                     persist, meta, scope)

    def _search_impl(self, query: str, pipeline: str = "auto", max_results: int = 10,
                     jev_overrides: dict[str, Any] | None = None, context_budget: int | None = None,
                     persist: bool = True, run_meta: dict[str, Any] | None = None,
                     scope: str | None = None) -> MemoryResult:
        if pipeline != "auto" and pipeline not in PIPELINES:
            raise ValueError(f"pipeline inválido: {pipeline}. Use um de {('auto',) + PIPELINES}")
        max_results = max(1, min(int(max_results), 50))
        query = query.strip()
        if not query:
            raise ValueError("query vazia")
        meta = dict(run_meta or {})
        run_id = meta.get("run_id") or uuid.uuid4().hex[:12]
        jcfg = replace(self.jev_cfg, **jev_overrides) if jev_overrides else self.jev_cfg
        parsed_scope = parse_scope(scope)
        if not parsed_scope.is_global:       # F9-01: saved notes declare their project in frontmatter
            parsed_scope.frontmatter_resolver = self._saved_note_project
        t0 = time.perf_counter()
        error = None

        # -- MEMORY OPTIMIZATION LAYER: pre-retrieval (freshness, analysis, routing, cache) ------
        opt = self.optimizer
        pre: dict[str, Any] = {}
        try:
            pre.update(opt.ensure_fresh(self))
        except Exception as exc:  # noqa: BLE001 — a failed freshness check never blocks a search
            pre["optimizer_errors"] = [f"freshness:{type(exc).__name__}"]
        plan = opt.plan(query, pipeline, self)
        # Opt-in economy rules (settings): inert unless the user enabled them -> default unchanged.
        plan, max_results, context_budget, eco_m = self._apply_economy(plan, max_results, context_budget, query)
        pre.update(eco_m)
        # T6.4: no-op unless ANAMNESIA_BUDGET_ENFORCE=1 (then may degrade a paid plan to baseline)
        plan, budget_m = self.budget_guard.apply(plan, self.db)
        pre.update(budget_m)
        pipeline = plan.pipeline
        cache_on = self.bench_cfg.cache_enabled
        # ANA-021: the key carries a digest of the effective configuration (stages, retrieval knobs,
        # JEV/optimizer config, graph.json identity), not only the vault fingerprint.
        ckey = None
        if cache_on:
            try:
                ckey = opt.cache_key(plan, max_results, parsed_scope.label(), context_budget, jev_overrides,
                                     extra=(opt.config_digest(self, plan),))
            except Exception as exc:  # noqa: BLE001 -- cannot digest the config -> do not cache
                pre.setdefault("optimizer_errors", []).append(f"config_digest:{type(exc).__name__}")
        if ckey is not None:
            hit = opt.cache.get(ckey)
            if hit is not None:
                # ANA-025: re-hash the delivered sources; an edit between searches invalidates the entry.
                if opt.guard_valid(self, hit[4] if len(hit) > 4 else None):
                    return self._from_cache(hit, query, run_id, plan, pre, t0, jcfg, meta, persist)
                opt.cache.invalidate(ckey)

        try:
            # Pipelines read gw.active_scope to drop out-of-scope candidates before the judge.
            self.active_scope = parsed_scope
            if pipeline in JEV_PIPELINES:
                jev = self.make_jev(jcfg) if jev_overrides else self.jev
                cands, full, m = PIPELINE_FUNCS[pipeline](self, query, max_results, jev=jev)
            else:
                cands, full, m = PIPELINE_FUNCS[pipeline](self, query, max_results)
        except Exception as exc:  # noqa: BLE001
            self.log.exception("pipeline %s failed", pipeline)
            cands, full, m, error = [], {}, {}, f"{type(exc).__name__}: {exc}"
        finally:
            self.active_scope = None
        tb = time.perf_counter()
        all_judged = m.pop("_all_candidates", None)
        # Defence in depth: scope is enforced inside the pipelines (before the judge, so it saves
        # tokens) AND again here, so a future pipeline that forgets about it cannot leak (§14, §40).
        if not parsed_scope.is_global:
            kept = [c for c in cands if parsed_scope.matches(c.source_file)]
            if len(kept) != len(cands):
                m["scope_leaked_blocked"] = len(cands) - len(kept)
            cands = kept
        m["scope"] = parsed_scope.label()
        # -- MEMORY OPTIMIZATION LAYER: post-retrieval (adaptive cut, near-dup, security flag,
        #    temporality, conflict demotion). The last two read the note frontmatter (read-only).
        cands, post = opt.post_filter(cands, plan, gw=self, query=query)
        rank_on = False
        if pipeline != "graphify_jev":          # ANAM-013: MG_MEMORY_RANK=v2 (default v1 = no-op, frozen pipeline untouched)
            try:
                from app.memory_store import model as _mm
                if _mm.rank_mode() == "v2":
                    from app.memory_store.store import get_store
                    cands, rm = _mm.rerank_candidates(get_store(), cands)
                    post.update(rm)
                    rank_on = True
            except Exception as exc:  # noqa: BLE001 — ranking is advisory; keep retrieval order on failure
                post.setdefault("optimizer_errors", []).append(f"memory_rank:{type(exc).__name__}")
        # -- OPTIONAL STAGES (§1.4/§5.5): reranking/compression/dedup/spotlighting, all off by
        # default. Never runs on graphify_jev (frozen reference pipeline).
        if pipeline != "graphify_jev":
            osc = self.optional_stages_cfg.resolved(pipeline)
            if osc.active_flags():
                try:
                    m.update(apply_optional_stages(query, cands, full, osc))
                except Exception as exc:  # noqa: BLE001 — an optional stage must never break search
                    m["optional_stages_errors"] = [f"{type(exc).__name__}: {exc}"]
        prov, prov_m = self.provenance_for(cands, plan.pipeline)
        from app.gateway.optimizer import FROZEN_PIPELINES
        # the frozen reference pipeline stays byte-identical: no unjudged attribute there (metric still recorded)
        context, sources, ctx_tokens = self.build_context(cands, full, context_budget, provenance=prov,
                                                          mark_unjudged=pipeline not in FROZEN_PIPELINES,
                                                          nonce=pipeline not in FROZEN_PIPELINES
                                                          and os.environ.get("MG_CONTEXT_NONCE", "0").strip().lower()
                                                          in ("1", "true", "on", "yes", "random"),
                                                          fit_query=query if (pipeline not in FROZEN_PIPELINES
                                                                              and get_flags(self).budget_fit) else None)
        t1 = time.perf_counter()

        before = m.get("candidate_tokens_before_filter") or 0
        jev_in = m.get("jev_input_tokens")
        is_jev = pipeline in JEV_PIPELINES
        jev_cost = cost_usd(jev_in, m.get("jev_output_tokens"), jcfg.model) if is_jev else 0.0
        # Tokens actually spent to answer one query, across EVERY stage that talks to a model.
        # context_reduction alone is misleading: a filter can shrink the final context while spending
        # far more tokens judging candidates. total_tokens_spent is the only honest cost signal.
        judge_tokens = (jev_in or 0) + (m.get("jev_output_tokens") or 0) if is_jev else 0
        total_spent = judge_tokens + ctx_tokens
        m.update({
            "metrics_version": METRICS_VERSION,
            "pipeline": pipeline,
            "candidates": m.get("documents_found", 0),
            "survivors": len(cands),
            "documents_sent_to_model": len(sources),
            "context_tokens": ctx_tokens,
            "context_tokens_after_filter": ctx_tokens,
            "context_reduction": round(1 - ctx_tokens / before, 4) if before else None,
            "judge_tokens": judge_tokens,
            "total_tokens_spent": total_spent,
            # >1 means the pipeline spends more tokens than it delivers as context (filtering overhead).
            "token_amplification": round(total_spent / ctx_tokens, 2) if ctx_tokens else None,
            "context_build_latency_ms": round((t1 - tb) * 1000, 1),
            "total_latency_ms": round((t1 - t0) * 1000, 1),
            "retrieval_tokens": before,
            "jev_tokens": judge_tokens,
            "jev_cost": jev_cost,
            "cache_enabled": self.bench_cfg.cache_enabled,
            "jev_mode": jcfg.mode if is_jev else None,
            "threshold": jcfg.relevance_threshold if is_jev else None,
            # Who actually called (Hermes, Claude Code, Codex…), distinct from `agent` (the
            # interface: mcp/rest/cli). Optional, caller-supplied, never inferred (§5.1).
            "client": meta.get("client"),
            **trace_metrics(),              # ANAM-012: trace_id/request_id additive in metrics_json
        })
        if is_jev:
            # ANA-023: fallback = judge failure signal (see app/services/judge_health.py)
            from app.services.judge_health import is_fallback_decision
            n_fb = sum(1 for c in cands if is_fallback_decision(c.decision))
            m["judge_fallback"] = 1 if (n_fb or (m.get("jev_fallback_used") or 0) > 0) else 0
            m["judge_fallback_blocks"] = n_fb
            m["judge_unjudged"] = int(m.get("candidates_unjudged") or (m.get("jev") or {}).get("candidates_unjudged") or 0)
        m.update(self._optimizer_metrics(plan, pre, post, cache_hit=False))
        m.update(prov_m)
        if error:
            m["error"] = error
        result = MemoryResult(query=query, pipeline=pipeline, context=context, sources=sources, metrics=m,
                              run_id=run_id, candidates=cands)
        if ckey is not None and not error and sources:
            ok, why = opt.cacheable(m, cands)
            guard = opt.source_guard(self, sources) if ok else None
            if ok and guard is not None:
                opt.cache.put(ckey, (context, list(sources), list(cands), dict(m), guard))
            else:
                m["result_cache_skipped"] = why or "no_guard"
        if rank_on and persist and sources:   # ANAM-013: usage feeds rank v2 (only behind the flag; never raises)
            from app.memory_store import model as _mm
            from app.memory_store.store import get_store
            m["memory_usage_recorded"] = _mm.record_delivered_usage(get_store(), sources, run_id=run_id)
        if persist:
            self._persist(result, jcfg, meta, error, all_judged)
        return result

    def economy_settings(self):
        from app.services.settings_store import economy_of
        try:
            return economy_of(self.db)
        except Exception:  # noqa: BLE001 - settings are optional; never break a search
            from app.gateway.economy import EconomySettings
            return EconomySettings()

    def _apply_economy(self, plan, max_results: int, context_budget: int | None, query: str):
        from app.gateway.economy import apply_economy
        eco = self.economy_settings()
        if not eco.active:
            return plan, max_results, context_budget, {}
        try:
            return apply_economy(eco, plan, max_results, context_budget, self.retrieval_cfg.model_context_budget,
                                 lambda: self.optimizer._verdict_size_estimate(self, query))
        except Exception as exc:  # noqa: BLE001
            return plan, max_results, context_budget, {"optimizer_errors": [f"economy:{type(exc).__name__}"]}

    def _optimizer_metrics(self, plan, pre: dict, post: dict, cache_hit: bool) -> dict:
        out = {
            "optimizer_enabled": self.optimizer.cfg.enabled,
            "optimizer_version": self.optimizer.cfg.version,
            "pipeline_requested": plan.requested,
            "route_reason": plan.reason,
            "query_complexity": plan.profile.complexity if plan.profile else None,
            "result_cache_hit": cache_hit,
            **pre, **post,
        }
        if self.optimizer.cfg.verdict_enabled and plan.requested == "auto":
            out["verdict_pipeline_chosen"] = plan.pipeline
            out["verdict_reason"] = plan.reason
            out["verdict_size_estimate"] = plan.verdict_size_estimate
        errs = list(pre.get("optimizer_errors", [])) + list(post.get("optimizer_errors", []))
        if errs:
            out["optimizer_errors"] = errs
        return out

    def _from_cache(self, hit, query, run_id, plan, pre, t0, jcfg, meta, persist) -> MemoryResult:
        """Serve an identical earlier result: no retrieval, no judge, no context build."""
        context, sources, cands, cached_m = hit[:4]
        m = dict(cached_m)
        m.update(self._optimizer_metrics(plan, pre, {}, cache_hit=True))
        m.update({"total_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                  "retrieval_latency_ms": 0.0, "judge_tokens": 0, "jev_tokens": 0, "jev_cost": 0.0,
                  "total_tokens_spent": m.get("context_tokens", 0),
                  # A cache hit reuses an earlier run's context but the CALLER can differ.
                  "client": meta.get("client"), **trace_metrics()})
        m.pop("error", None)
        result = MemoryResult(query=query, pipeline=plan.pipeline, context=context, sources=list(sources),
                              metrics=m, run_id=run_id, candidates=list(cands))
        if persist:
            self._persist(result, jcfg, meta, None, None)
        return result

    def _persist(self, r: MemoryResult, jcfg: JevConfig, meta: dict, error: str | None, all_judged=None) -> None:
        session_id = meta.get("session_id") or "adhoc"
        self.db.create_session(session_id, meta.get("kind", "search"), {})
        row = {
            "run_id": r.run_id, "session_id": session_id, "created_at": time.time(),
            "question_id": meta.get("question_id"), "query": r.query, "pipeline": r.pipeline,
            "agent": meta.get("agent"), "provider": meta.get("provider"), "model": meta.get("model"),
            "mode": meta.get("mode", "retrieval"), "repetition": meta.get("repetition", 0),
            "warmup": int(bool(meta.get("warmup"))), "order_index": meta.get("order_index"),
            "threshold": r.metrics.get("threshold"), "jev_mode": r.metrics.get("jev_mode"),
            "jev_model": jcfg.model if r.pipeline in JEV_PIPELINES else None,
            "cache_enabled": int(self.bench_cfg.cache_enabled),
            "config_json": {"jev": asdict(jcfg), "retrieval": {k: str(v) for k, v in asdict(self.retrieval_cfg).items()}},
            "metrics_json": r.metrics, "sources_json": [s.to_dict() for s in r.sources],
            "context": r.context, "error": error,
        }
        # store every candidate JEV saw (incl. dropped) so false negatives can be marked later (§25)
        cands = [c.to_dict() for c in (all_judged if all_judged is not None else r.candidates)]
        line = {k: row[k] for k in ("session_id", "run_id", "question_id", "agent", "provider",
                                    "model", "pipeline")} | {"total_latency_ms": r.metrics.get("total_latency_ms"),
                                                              **trace_metrics()}
        if self._bench_log is not None and getattr(self.db, "_writer", None) is not None:
            self._persist_async(row, cands, line)
        else:
            self.db.save_run(row, cands)
            jsonl("benchmark", line)

    def _persist_async(self, row: dict, cands: list[dict], line: dict) -> None:
        """ANAM-019: enqueue (snapshot of metrics_json taken now: callers may mutate r.metrics afterwards)."""
        row["metrics_json"] = json.dumps(row["metrics_json"], default=str, ensure_ascii=False)
        if self.db._writer._q.qsize() >= self._persist_max_queue:   # backpressure instead of unbounded growth
            self.db.flush(5.0)
        self.db.save_run(row, cands)
        self._bench_log.put(line)

    def flush_persistence(self, timeout: float = 30.0) -> bool:
        """Block until every enqueued run / jsonl line is on disk (read-your-writes, shutdown, tests)."""
        try:
            ok = bool(self.db.flush(timeout))
            if self._bench_log is not None:
                ok = self._bench_log.flush(timeout) and ok
            return ok
        except Exception as exc:  # noqa: BLE001
            self.log.warning("flush_persistence failed: %s", type(exc).__name__)
            return False

    def close(self) -> None:
        """Flush and stop the background writers (idempotent)."""
        self.flush_persistence()
        if self._bench_log is not None:
            self._bench_log.stop()
            self._bench_log = None
        try:
            atexit.unregister(self._atexit_cb)
        except Exception:  # noqa: BLE001
            pass

    def metrics(self) -> dict:
        from app.benchmark.statistics import aggregate_stats
        return aggregate_stats(self.db)

    def system_info(self) -> dict:
        from app.adapters.registry import detect_all
        from app.services.jev import sdk_version
        return {
            "vault": str(self.vault.root),
            "vault_exists": self.vault.exists(),
            "markdown_files": len(self.vault.list_markdown()),
            "graphify": self.graphify.version(),
            "graph_path": str(self.graphify.graph_path),
            "jev_sdk": sdk_version(), "jev_model": self.jev_cfg.model, "jev_mode": self.jev_cfg.mode,
            "cache_enabled": self.bench_cfg.cache_enabled, "profile": self.bench_cfg.profile,
            "db": self.db.path, "integrations": detect_all(),
            "optimizer": {"enabled": self.optimizer.cfg.enabled, "version": self.optimizer.cfg.version,
                          "result_cache": self.optimizer.cache.stats(),
                          "index_rebuilds": self.optimizer.index_rebuilds},
        }
