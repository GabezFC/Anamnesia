"""MemoryGateway — central orchestration service (§31). Agent- and model-agnostic.

search()        retrieval + filtering + context building for one pipeline
retrieve()      raw candidates of a pipeline (no filtering)
filter()        JEV judgment over given candidates
build_context() ModelContextBuilder over candidates
benchmark()     delegated to app.benchmark.runner
metrics()       aggregate statistics from SQLite
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from config.benchmark import BenchmarkConfig
from config.jev import JevConfig
from config.retrieval import RetrievalConfig
from app.database.db import Database
from app.gateway.context_builder import ModelContextBuilder
from app.retrieval.baseline import BaselineIndex
from app.retrieval.pipelines import PIPELINE_FUNCS
from app.schemas.models import PIPELINES, MemoryResult
from app.services.graphify import GraphifyService
from app.services.jev import JevService
from app.services.metrics import get_logger, jsonl
from app.services.obsidian import ObsidianVault
from app.services.pricing import cost_usd


class MemoryGateway:
    def __init__(self, retrieval_cfg: RetrievalConfig | None = None, jev_cfg: JevConfig | None = None,
                 bench_cfg: BenchmarkConfig | None = None, db: Database | None = None,
                 jev_backend=None, graphify_service: GraphifyService | None = None):
        self.retrieval_cfg = retrieval_cfg or RetrievalConfig()
        self.jev_cfg = jev_cfg or JevConfig()
        self.bench_cfg = bench_cfg or BenchmarkConfig()
        self.log = get_logger()
        self.vault = ObsidianVault(self.retrieval_cfg.vault_path, self.retrieval_cfg.excluded_dirs)
        if not self.vault.exists():
            raise FileNotFoundError(f"Vault não encontrado: {self.vault.root}")
        self.db = db or Database(self.bench_cfg.db_path)
        db_path = Path(self.db.path).resolve()
        if self.vault.root in db_path.parents:
            raise PermissionError("benchmark.db não pode ficar dentro do vault (§58)")
        self.baseline = BaselineIndex(self.vault)
        self.graphify = graphify_service or GraphifyService(
            self.vault, self.retrieval_cfg.mirror_dir, self.retrieval_cfg.graphify_bin,
            self.retrieval_cfg.graphify_query_budget, self.retrieval_cfg.graphify_timeout_s)
        self._jev_backend = jev_backend
        self.jev = self.make_jev(self.jev_cfg)

    # -- helpers ------------------------------------------------------------------
    def make_jev(self, cfg: JevConfig, cache: bool | None = None) -> JevService:
        use_cache = self.bench_cfg.cache_enabled if cache is None else cache
        return JevService(cfg, backend=self._jev_backend,
                          cache_get=self.db.cache_get if use_cache else None,
                          cache_put=self.db.cache_put if use_cache else None,
                          logger=lambda e: jsonl("jev", e))

    def warm(self) -> dict:
        t0 = time.perf_counter()
        self.baseline.build()
        g = self.graphify.build()
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
        b = ModelContextBuilder(budget or self.retrieval_cfg.model_context_budget,
                                self.retrieval_cfg.per_source_max_tokens)
        return b.build(candidates, full_texts)

    def search(self, query: str, pipeline: str = "graphify_jev", max_results: int = 10,
               jev_overrides: dict[str, Any] | None = None, context_budget: int | None = None,
               persist: bool = True, run_meta: dict[str, Any] | None = None) -> MemoryResult:
        if pipeline not in PIPELINES:
            raise ValueError(f"pipeline inválido: {pipeline}. Use um de {PIPELINES}")
        max_results = max(1, min(int(max_results), 50))
        query = query.strip()
        if not query:
            raise ValueError("query vazia")
        meta = dict(run_meta or {})
        run_id = meta.get("run_id") or uuid.uuid4().hex[:12]
        jcfg = replace(self.jev_cfg, **jev_overrides) if jev_overrides else self.jev_cfg
        t0 = time.perf_counter()
        error = None
        try:
            if pipeline == "graphify_jev":
                jev = self.make_jev(jcfg) if jev_overrides else self.jev
                cands, full, m = PIPELINE_FUNCS[pipeline](self, query, max_results, jev=jev)
            else:
                cands, full, m = PIPELINE_FUNCS[pipeline](self, query, max_results)
        except Exception as exc:  # noqa: BLE001
            self.log.exception("pipeline %s failed", pipeline)
            cands, full, m, error = [], {}, {}, f"{type(exc).__name__}: {exc}"
        tb = time.perf_counter()
        all_judged = m.pop("_all_candidates", None)
        context, sources, ctx_tokens = self.build_context(cands, full, context_budget)
        t1 = time.perf_counter()

        before = m.get("candidate_tokens_before_filter") or 0
        jev_in = m.get("jev_input_tokens")
        jev_cost = cost_usd(jev_in, m.get("jev_output_tokens"), jcfg.model) if pipeline == "graphify_jev" else 0.0
        m.update({
            "pipeline": pipeline,
            "candidates": m.get("documents_found", 0),
            "survivors": len(cands),
            "documents_sent_to_model": len(sources),
            "context_tokens": ctx_tokens,
            "context_tokens_after_filter": ctx_tokens,
            "context_reduction": round(1 - ctx_tokens / before, 4) if before else None,
            "context_build_latency_ms": round((t1 - tb) * 1000, 1),
            "total_latency_ms": round((t1 - t0) * 1000, 1),
            "retrieval_tokens": before,
            "jev_tokens": (jev_in or 0) + (m.get("jev_output_tokens") or 0) if pipeline == "graphify_jev" else 0,
            "jev_cost": jev_cost,
            "cache_enabled": self.bench_cfg.cache_enabled,
            "jev_mode": jcfg.mode if pipeline == "graphify_jev" else None,
            "threshold": jcfg.relevance_threshold if pipeline == "graphify_jev" else None,
        })
        if error:
            m["error"] = error
        result = MemoryResult(query=query, pipeline=pipeline, context=context, sources=sources, metrics=m,
                              run_id=run_id, candidates=cands)
        if persist:
            self._persist(result, jcfg, meta, error, all_judged)
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
            "jev_model": jcfg.model if r.pipeline == "graphify_jev" else None,
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
        }
