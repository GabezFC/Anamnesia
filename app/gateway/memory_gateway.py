"""MemoryGateway — central orchestration service (§31). Agent- and model-agnostic.

search()        retrieval + filtering + context building for one pipeline
retrieve()      raw candidates of a pipeline (no filtering)
filter()        JEV judgment over given candidates
build_context() ModelContextBuilder over candidates
benchmark()     delegated to app.benchmark.runner
metrics()       aggregate statistics from SQLite
"""
from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from config.benchmark import BenchmarkConfig
from config.jev import JevConfig
from config.optimization import OptimizationConfig, OptionalStagesConfig
from config.optimizer import OptimizerConfig
from config.retrieval import RetrievalConfig
from app.database.db import Database
from app.gateway.context_builder import ModelContextBuilder
from app.gateway.optimizer import MemoryOptimizer
from app.retrieval.baseline import BaselineIndex
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
# calibration factor in app/gateway/token_budget.py:estimate_tokens (§5.5 item 9). Lets a consumer
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


class MemoryGateway:
    def __init__(self, retrieval_cfg: RetrievalConfig | None = None, jev_cfg: JevConfig | None = None,
                 bench_cfg: BenchmarkConfig | None = None, db: Database | None = None,
                 jev_backend=None, graphify_service: GraphifyService | None = None,
                 opt_cfg: OptimizationConfig | None = None, optimizer_cfg: OptimizerConfig | None = None,
                 optional_stages_cfg: OptionalStagesConfig | None = None):
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
        # Cache isolation handle. "" in production; a benchmark sets it so its arms cannot read
        # judgements cached by a previous run (see app/services/jev.py cache_key).
        self.cache_namespace = ""
        self.log = get_logger()
        self.vault = ObsidianVault(self.retrieval_cfg.vault_path, self.retrieval_cfg.excluded_dirs)
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault não encontrado: {self.vault.root}")
        self.db = db or Database(self.bench_cfg.db_path, compress_context=self.bench_cfg.db_compress_context)
        db_path = Path(self.db.path).resolve()
        if self.vault.root in db_path.parents:
            raise PermissionError("benchmark.db não pode ficar dentro do vault (§58)")
        self.baseline = BaselineIndex(self.vault)
        self.graphify = graphify_service or GraphifyService(
            self.vault, self.retrieval_cfg.mirror_dir, self.retrieval_cfg.graphify_bin,
            self.retrieval_cfg.graphify_query_budget, self.retrieval_cfg.graphify_timeout_s)
        self._jev_backend = jev_backend
        self.jev = self.make_jev(self.jev_cfg)
        # Lazy in-memory view of graph.json used by the hybrid retriever (reloads on mtime change).
        self.graph_index = GraphIndex(self.graphify.graph_path)

    # -- scope (contextvar-backed, §5.4) -------------------------------------------
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

    def build_context(self, candidates, full_texts=None, budget: int | None = None):
        oc = self.optimizer.cfg
        b = ModelContextBuilder(budget or self.retrieval_cfg.model_context_budget,
                                self.retrieval_cfg.per_source_max_tokens,
                                compact_headers=oc.enabled and oc.compact_headers,
                                section_max_chars=oc.header_section_max_chars)
        return b.build(candidates, full_texts)

    def search(self, query: str, pipeline: str = "auto", max_results: int = 10,
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
        pipeline = plan.pipeline
        cache_on = self.bench_cfg.cache_enabled
        ckey = opt.cache_key(plan, max_results, parsed_scope.label(), context_budget, jev_overrides) \
            if cache_on else None
        if ckey is not None:
            hit = opt.cache.get(ckey)
            if hit is not None:
                return self._from_cache(hit, query, run_id, plan, pre, t0, jcfg, meta, persist)

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
        # -- MEMORY OPTIMIZATION LAYER: post-retrieval (adaptive cut, near-dup, security flag) ---
        cands, post = opt.post_filter(cands, plan)
        # -- OPTIONAL STAGES (§1.4/§5.5): reranking/compression/dedup/spotlighting, all off by
        # default. Never runs on graphify_jev (frozen reference pipeline).
        if pipeline != "graphify_jev":
            osc = self.optional_stages_cfg.resolved()
            if osc.active_flags():
                try:
                    m.update(apply_optional_stages(query, cands, full, osc))
                except Exception as exc:  # noqa: BLE001 — an optional stage must never break search
                    m["optional_stages_errors"] = [f"{type(exc).__name__}: {exc}"]
        context, sources, ctx_tokens = self.build_context(cands, full, context_budget)
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
        })
        m.update(self._optimizer_metrics(plan, pre, post, cache_hit=False))
        if error:
            m["error"] = error
        result = MemoryResult(query=query, pipeline=pipeline, context=context, sources=sources, metrics=m,
                              run_id=run_id, candidates=cands)
        if ckey is not None and not error and sources:
            opt.cache.put(ckey, (context, list(sources), list(cands), dict(m)))
        if persist:
            self._persist(result, jcfg, meta, error, all_judged)
        return result

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
        context, sources, cands, cached_m = hit
        m = dict(cached_m)
        m.update(self._optimizer_metrics(plan, pre, {}, cache_hit=True))
        m.update({"total_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                  "retrieval_latency_ms": 0.0, "judge_tokens": 0, "jev_tokens": 0, "jev_cost": 0.0,
                  "total_tokens_spent": m.get("context_tokens", 0),
                  # A cache hit reuses an earlier run's context but the CALLER can differ.
                  "client": meta.get("client")})
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
        self.db.save_run(row, cands)
        jsonl("benchmark", {k: row[k] for k in ("session_id", "run_id", "question_id", "agent", "provider",
                                                "model", "pipeline")} | {"total_latency_ms": r.metrics.get("total_latency_ms")})

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
