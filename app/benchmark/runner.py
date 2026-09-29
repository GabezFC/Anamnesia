"""Benchmark runner (§39–§51, §71, §82–§88, §92).

Experiment unit = question + retrieval_pipeline + consumer_agent + model + configuration.
- retrieval-only benchmark: pipelines only, no generation (Memory Retrieval Benchmark, §86).
- end-to-end benchmark: retrieval + JEV + generation by ONE consumer at a time (§87). Within a consumer
  the prompt/model/params are identical across pipelines; only retrieval changes (§51, §84).
- pipeline order randomized per question with a recorded seed (§50); optional warm-up excluded from stats (§48).
- BENCHMARK_MODE: all caches off, recorded as cache_enabled=false (§47).
"""
from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import replace
from typing import Any, Callable

from config.benchmark import ALLOWED_REPETITIONS, SWEEP_THRESHOLDS
from app.gateway.context_builder import render_prompt
from app.gateway.token_budget import estimate_tokens
from app.schemas.models import JEV_PIPELINES, PIPELINES
from app.services.metrics import jsonl
from app.services.pricing import add_costs, break_even, cost_usd


def load_questions(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def estimate_plan(n_questions: int, pipelines: list[str], consumers: list[dict], repetitions: int,
                  avg_jev_tokens: float | None = None) -> dict:
    """§82: runs (and JEV cost when a previous average exists) before executing."""
    n_consumers = max(1, len(consumers))
    runs = n_questions * len(pipelines) * n_consumers * repetitions
    jev_pipelines_requested = sum(1 for p in pipelines if p in JEV_PIPELINES)
    jev_runs = n_questions * n_consumers * repetitions * jev_pipelines_requested
    est_cost = None
    if avg_jev_tokens is not None:
        est_cost = cost_usd(int(avg_jev_tokens * jev_runs), 0, "jev-1.13.0")
    return {"estimated_runs": runs, "jev_runs": jev_runs, "estimated_jev_cost_usd": est_cost,
            "estimated_model_cost_usd": None,  # needs provider prices; local models are 0
            "formula": f"{n_questions} × {len(pipelines)} × {n_consumers} × {repetitions}"}


class BenchmarkRunner:
    def __init__(self, gateway, progress: Callable[[dict], None] | None = None):
        self.gw = gateway
        self.progress = progress or (lambda _e: None)

    def _generate(self, consumer_spec: dict, context: str, question: str) -> dict:
        from app.adapters.registry import get_consumer
        consumer = get_consumer(consumer_spec["agent"], consumer_spec.get("provider"), consumer_spec.get("model"))
        prompt = render_prompt(context, question)
        g = consumer.generate(prompt)
        is_agent = consumer_spec["agent"] != "generic"
        model_cost = cost_usd(g.input_tokens, g.output_tokens, g.model, consumer_spec.get("provider"))
        if is_agent and g.agent_cost is not None:
            model_cost = g.agent_cost
        return {
            "answer": g.answer, "error": g.error,
            "generation_latency_ms": g.latency_ms,
            "prompt_tokens_estimate": estimate_tokens(prompt),
            "model_input_tokens": g.input_tokens, "model_output_tokens": g.output_tokens,
            # for full agents, input includes system prompt + tool schemas: agent overhead (§43)
            "agent_tokens": g.agent_tokens if is_agent else None,
            "agent_overhead_tokens": (g.input_tokens - estimate_tokens(prompt))
            if (is_agent and g.input_tokens is not None) else None,
            "model_cost": model_cost, "consumer_provider": g.provider, "consumer_model": g.model,
            "agent_meta": g.raw_meta,
        }

    def run(self, questions: list[dict], pipelines: list[str] | None = None, consumers: list[dict] | None = None,
            repetitions: int = 1, warmup: bool = True, jev_overrides: dict | None = None,
            max_results: int = 10, seed: int | None = None, session_id: str | None = None,
            notes: str = "") -> dict:
        pipelines = [p for p in (pipelines or list(PIPELINES)) if p in PIPELINES]
        if repetitions not in ALLOWED_REPETITIONS:
            raise ValueError(f"repetitions deve ser um de {ALLOWED_REPETITIONS}")
        consumers = consumers or []  # [] -> retrieval-only benchmark
        mode = "end_to_end" if consumers else "retrieval"
        seed = self.gw.bench_cfg.seed if seed is None else seed
        rng = random.Random(seed)
        session_id = session_id or f"bench-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        prev_cache = self.gw.bench_cfg.benchmark_mode
        self.gw.bench_cfg.benchmark_mode = True  # §47: every cache off during benchmark
        self.gw.jev = self.gw.make_jev(self.gw.jev_cfg)
        config = {"pipelines": pipelines, "consumers": consumers, "repetitions": repetitions, "seed": seed,
                  "jev": {**self.gw.jev_cfg.__dict__, **(jev_overrides or {})}, "mode": mode,
                  "cache_enabled": False, "max_results": max_results,
                  "plan": estimate_plan(len(questions), pipelines, consumers, repetitions)}
        self.gw.db.create_session(session_id, mode, config, notes)
        results: list[dict] = []
        try:
            if warmup and questions:
                wq = questions[0]
                for p in pipelines:
                    self.gw.search(wq["question"], p, max_results, jev_overrides=jev_overrides,
                                   run_meta={"session_id": session_id, "question_id": wq.get("id"), "warmup": True,
                                             "kind": mode, "mode": "warmup"})
            for spec in (consumers or [None]):
                for rep in range(1, repetitions + 1):
                    for q in questions:
                        order = pipelines[:]
                        rng.shuffle(order)
                        for idx, p in enumerate(order):
                            results.append(self._one(session_id, q, p, spec, rep, idx, jev_overrides, max_results,
                                                     mode))
        finally:
            self.gw.bench_cfg.benchmark_mode = prev_cache
            self.gw.jev = self.gw.make_jev(self.gw.jev_cfg)
        return {"session_id": session_id, "mode": mode, "runs": len(results), "config": config,
                "comparison": compare(results)}

    def _one(self, session_id, q, pipeline, spec, rep, idx, jev_overrides, max_results, mode) -> dict:
        meta = {"session_id": session_id, "question_id": q.get("id"), "repetition": rep, "order_index": idx,
                "kind": mode, "mode": mode, "agent": spec["agent"] if spec else None,
                "provider": spec.get("provider") if spec else None, "model": spec.get("model") if spec else None}
        r = self.gw.search(q["question"], pipeline, max_results, jev_overrides=jev_overrides, run_meta=meta)
        m = r.metrics
        m["retrieval_total_latency_ms"] = m["total_latency_ms"]
        m["expected_sources_found"] = _expected_hits(q, r)
        if spec:
            gen = self._generate(spec, r.context, q["question"])
            m.update({k: v for k, v in gen.items() if k not in ("answer", "error", "agent_meta")})
            m["agent_meta"] = gen["agent_meta"]
            m["total_latency_ms"] = round(m["retrieval_total_latency_ms"] + gen["generation_latency_ms"], 1)
            m["total_cost"] = add_costs(m.get("jev_cost"), gen["model_cost"])
            m["total_tokens"] = None if gen["model_input_tokens"] is None else (
                gen["model_input_tokens"] + (gen["model_output_tokens"] or 0) + (m.get("jev_tokens") or 0))
            self.gw.db.update_run_answer(r.run_id, gen["answer"], m, gen["error"])
            jsonl("agents", {"session_id": session_id, "run_id": r.run_id, "question_id": q.get("id"),
                             "agent": spec["agent"], "provider": spec.get("provider"), "model": spec.get("model"),
                             "pipeline": pipeline, "latency_ms": gen["generation_latency_ms"],
                             "input_tokens": gen["model_input_tokens"], "error": gen["error"]})
        else:
            m["total_cost"] = m.get("jev_cost")
            self.gw.db.update_run_answer(r.run_id, None, m, m.get("error"))
        out = {"run_id": r.run_id, "question_id": q.get("id"), "pipeline": pipeline, "repetition": rep,
               "agent": meta["agent"], "model": meta["model"], "metrics": m,
               "sources": [s.file for s in r.sources]}
        self.progress(out)
        return out

    def threshold_sweep(self, questions: list[dict], thresholds=SWEEP_THRESHOLDS, max_results: int = 10) -> dict:
        """§71/§92: JEV is called ONCE per question (scores do not depend on the threshold);
        routing is then re-applied in code for each threshold. Honest and cheap."""
        from app.retrieval.pipelines import _graphify_candidates
        from app.services.jev import route, survives
        session_id = f"sweep-{time.strftime('%Y%m%d-%H%M%S')}"
        self.gw.bench_cfg.benchmark_mode = True
        jev = self.gw.make_jev(self.gw.jev_cfg, cache=False)
        per_q = []
        try:
            for q in questions:
                uniq, gm = _graphify_candidates(self.gw, q["question"])
                _, jm = jev.evaluate(q["question"], uniq)
                per_q.append((q, uniq, gm, jm.to_dict()))
        finally:
            self.gw.bench_cfg.benchmark_mode = False
        fn = self.gw.db.query("SELECT candidate_id, question FROM false_negatives")
        jev_tokens_total = sum((jm.get("input_tokens") or 0) for *_, jm in per_q)
        rows = []
        for t in thresholds:
            # The swept value is the effective SURVIVAL cutoff: with REVIEW→KEEP the survival boundary is
            # review_threshold, so both bounds are set to t (otherwise every row would be identical).
            cfg = replace(self.gw.jev_cfg, relevance_threshold=t, review_threshold=t)
            kept = ctx = dropped = fns = 0
            recalls = []
            for q, uniq, _, _ in per_q:
                surv = [c for c in uniq if survives(route(c.relevance, c.injection, cfg), cfg)]
                kept += len(surv)
                dropped += len(uniq) - len(surv)
                context, sources, tokens = self.gw.build_context(surv)
                ctx += tokens
                surv_ids = {c.candidate_id for c in surv}
                dropped_ids = {c.candidate_id for c in uniq} - surv_ids
                fns += sum(1 for f in fn if f["question"] == q["question"] and f["candidate_id"] in dropped_ids)
                exp = q.get("expected_sources") or []
                if exp:
                    got = {s.file for s in sources}
                    recalls.append(sum(e in got for e in exp) / len(exp))
            rows.append({"threshold": t, "documents_kept": kept, "context_tokens": ctx,
                         "jev_cost": cost_usd(jev_tokens_total, 0, self.gw.jev_cfg.model),
                         "jev_latency_ms": round(sum(jm["latency_ms"] for *_, jm in per_q), 1),
                         "model_cost": None,  # depends on the consumer; measure with end-to-end
                         "expected_source_recall": round(sum(recalls) / len(recalls), 3) if recalls else None,
                         "false_negative_rate": round(fns / dropped, 4) if dropped else None})
        self.gw.db.create_session(session_id, "threshold_sweep", {"thresholds": list(thresholds), "rows": rows})
        return {"session_id": session_id, "questions": len(questions), "rows": rows,
                "note": "threshold = corte efetivo de sobrevivência (relevance_threshold = review_threshold = t)"}


def _expected_hits(q: dict, r) -> dict | None:
    exp = q.get("expected_sources")
    if not exp:
        return None
    got = {s.file for s in r.sources}
    hits = [e for e in exp if e in got]
    return {"expected": len(exp), "found": len(hits), "recall": round(len(hits) / len(exp), 3)}


def compare(results: list[dict]) -> dict:
    """Per question & consumer: side-by-side table + Graphify vs Graphify+JEV break-even. No verdicts (§91)."""
    table: dict[str, dict] = {}
    for r in results:
        key = f"{r['question_id']}|{r.get('agent') or 'retrieval'}|{r.get('model') or '-'}|rep{r['repetition']}"
        table.setdefault(key, {})[r["pipeline"]] = r["metrics"]
    out = {}
    for key, per in table.items():
        row = {p: {k: per[p].get(k) for k in ("total_latency_ms", "documents_found", "documents_sent_to_model",
                                             "candidate_tokens_before_filter", "context_tokens", "jev_tokens",
                                             "model_input_tokens", "model_output_tokens", "total_cost",
                                             "expected_sources_found")} for p in per}
        if "graphify" in per and "graphify_jev" in per:
            row["graphify_vs_graphify_jev"] = break_even(per["graphify"], per["graphify_jev"])
        out[key] = row
    return out
