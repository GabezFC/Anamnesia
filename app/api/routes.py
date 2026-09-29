"""REST API (§6). FastAPI. Read + benchmark operations only; nothing writes to the vault."""
from __future__ import annotations

import json
import threading
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.adapters.registry import detect_all
from app.benchmark.evaluator import validate_evaluation, validate_label
from app.benchmark.runner import BenchmarkRunner, estimate_plan, load_questions
from app.benchmark.statistics import aggregate_stats

router = APIRouter()
_state: dict = {"gateway": None, "jobs": {}}
Pipeline = Literal["auto", "baseline", "graphify", "graphify_jev"]
BenchPipeline = Literal["baseline", "graphify", "graphify_jev"]


def gw():
    if _state["gateway"] is None:
        raise HTTPException(503, "gateway não inicializado")
    return _state["gateway"]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    # "auto" = Memory Optimization Layer routing (cheapest pipeline measured to hold recall).
    pipeline: Pipeline = "auto"
    max_results: int = Field(10, ge=1, le=50)
    jev_mode: Literal["performance", "strict"] | None = None
    threshold: float | None = Field(None, ge=0, le=1)
    review_action: Literal["keep", "drop"] | None = None
    context_budget: int | None = Field(None, ge=200, le=100000)
    include_candidates: bool = False
    # Memory scoping (§14): "projeto:<slug>", comma-separated for several projects,
    # "area:<Area>", or omitted/"global" for the whole brain.
    scope: str | None = Field(None, max_length=500)


class ConsumerSpec(BaseModel):
    agent: Literal["hermes", "claude_code", "codex", "opencode", "generic"]
    provider: str | None = None
    model: str | None = None


class BenchmarkRequest(BaseModel):
    question_ids: list[str] | None = None
    questions: list[str] | None = None  # ad-hoc questions
    pipelines: list[BenchPipeline] | None = None
    consumers: list[ConsumerSpec] = []
    repetitions: Literal[1, 3, 5, 10] = 1
    warmup: bool = True
    jev_mode: Literal["performance", "strict"] | None = None
    threshold: float | None = Field(None, ge=0, le=1)
    max_results: int = Field(10, ge=1, le=50)
    notes: str = ""
    background: bool = False


def _overrides(jev_mode=None, threshold=None, review_action=None) -> dict | None:
    o = {}
    if jev_mode:
        o["mode"] = jev_mode
    if threshold is not None:
        o["relevance_threshold"] = threshold
        o["review_threshold"] = min(threshold, gw().jev_cfg.review_threshold)
    if review_action:
        o["review_action"] = review_action
    return o or None


def _search(req: SearchRequest, pipeline: str):
    try:
        r = gw().search(req.query, pipeline, req.max_results,
                        jev_overrides=_overrides(req.jev_mode, req.threshold, req.review_action),
                        context_budget=req.context_budget, scope=req.scope,
                        run_meta={"kind": "api", "agent": "rest"})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return r.to_dict(include_candidates=req.include_candidates)


@router.get("/health")
def health():
    g = _state["gateway"]
    return {"status": "ok" if g else "starting", "vault_exists": bool(g and g.vault.exists())}


@router.post("/memory/search")
def memory_search(req: SearchRequest):
    return _search(req, req.pipeline)


@router.post("/memory/search/baseline")
def memory_search_baseline(req: SearchRequest):
    return _search(req, "baseline")


@router.post("/memory/search/graphify")
def memory_search_graphify(req: SearchRequest):
    return _search(req, "graphify")


@router.post("/memory/search/graphify-jev")
def memory_search_graphify_jev(req: SearchRequest):
    return _search(req, "graphify_jev")


def _questions(req: BenchmarkRequest) -> list[dict]:
    if req.questions:
        return [{"id": f"adhoc{i + 1:02d}", "question": q} for i, q in enumerate(req.questions)]
    qs = load_questions(gw().bench_cfg.questions_path)
    if req.question_ids:
        qs = [q for q in qs if q["id"] in set(req.question_ids)]
    return qs


def _run_benchmark(req: BenchmarkRequest, pipelines):
    runner = BenchmarkRunner(gw())
    qs = _questions(req)
    if not qs:
        raise HTTPException(422, "nenhuma pergunta selecionada")
    kwargs = dict(pipelines=pipelines, consumers=[c.model_dump() for c in req.consumers],
                  repetitions=req.repetitions, warmup=req.warmup, max_results=req.max_results,
                  jev_overrides=_overrides(req.jev_mode, req.threshold), notes=req.notes)
    if not req.background:
        return runner.run(qs, **kwargs)
    job = uuid.uuid4().hex[:8]
    _state["jobs"][job] = {"status": "running", "progress": []}

    def work():
        try:
            runner.progress = lambda e: _state["jobs"][job]["progress"].append(
                {k: e[k] for k in ("question_id", "pipeline", "run_id")})
            _state["jobs"][job].update(status="done", result=runner.run(qs, **kwargs))
        except Exception as exc:  # noqa: BLE001
            _state["jobs"][job].update(status="error", error=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job, "status": "running"}


@router.post("/benchmark/run")
def benchmark_run(req: BenchmarkRequest):
    return _run_benchmark(req, req.pipelines or ["graphify_jev"])


@router.post("/benchmark/run-all")
def benchmark_run_all(req: BenchmarkRequest):
    return _run_benchmark(req, ["baseline", "graphify", "graphify_jev"])


@router.post("/benchmark/estimate")
def benchmark_estimate(req: BenchmarkRequest):
    # Average real JEV input tokens per graphify_jev run from history (§82: "quando houver dados suficientes").
    rows = gw().db.query("SELECT metrics_json FROM runs WHERE pipeline='graphify_jev' AND warmup=0 "
                         "ORDER BY created_at DESC LIMIT 200")
    toks = [json.loads(r["metrics_json"]).get("jev_input_tokens") for r in rows if r["metrics_json"]]
    toks = [t for t in toks if t]
    avg = sum(toks) / len(toks) if toks else None
    return estimate_plan(len(_questions(req)), req.pipelines or ["baseline", "graphify", "graphify_jev"],
                         [c.model_dump() for c in req.consumers], req.repetitions, avg_jev_tokens=avg)


@router.get("/benchmark/jobs/{job_id}")
def benchmark_job(job_id: str):
    j = _state["jobs"].get(job_id)
    if not j:
        raise HTTPException(404, "job não encontrado")
    return j


@router.post("/benchmark/threshold-sweep")
def threshold_sweep(req: BenchmarkRequest):
    return BenchmarkRunner(gw()).threshold_sweep(_questions(req))


@router.get("/benchmark/runs")
def benchmark_runs(limit: int = 100, session_id: str | None = None):
    return gw().db.list_runs(limit, session_id)


@router.get("/benchmark/runs/{run_id}")
def benchmark_run_detail(run_id: str):
    r = gw().db.get_run(run_id)
    if not r:
        raise HTTPException(404, "run não encontrado")
    return r


@router.get("/benchmark/sessions")
def benchmark_sessions(limit: int = 50):
    return gw().db.list_sessions(limit)


@router.get("/benchmark/stats")
def benchmark_stats(session_id: str | None = None):
    return aggregate_stats(gw().db, session_id)


@router.get("/benchmark/questions")
def benchmark_questions():
    return load_questions(gw().bench_cfg.questions_path)


class FalseNegativeRequest(BaseModel):
    run_id: str
    candidate_id: str


@router.post("/feedback/false-negative")
def mark_false_negative(req: FalseNegativeRequest):
    try:
        return gw().db.mark_false_negative(req.run_id, req.candidate_id)
    except KeyError as exc:
        raise HTTPException(404, f"não encontrado: {exc}") from exc


class LabelRequest(BaseModel):
    run_id: str
    source_file: str
    label: str


@router.post("/feedback/label")
def add_label(req: LabelRequest):
    try:
        validate_label(req.label)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    gw().db.add_label(req.run_id, req.source_file, req.label)
    return {"ok": True}


class EvaluationRequest(BaseModel):
    run_id: str
    question_id: str | None = None
    agent: str | None = None
    model: str | None = None
    pipeline: str | None = None
    accuracy: int | None = Field(None, ge=1, le=5)
    completeness: int | None = Field(None, ge=1, le=5)
    groundedness: int | None = Field(None, ge=1, le=5)
    citation_quality: int | None = Field(None, ge=1, le=5)
    notes: str | None = None


@router.post("/feedback/evaluation")
def add_evaluation(req: EvaluationRequest):
    gw().db.add_evaluation(validate_evaluation(req.model_dump()))
    return {"ok": True}


@router.get("/system/info")
def system_info():
    return gw().system_info()


@router.get("/system/integrations")
def integrations(refresh: bool = False):
    return detect_all(refresh)


@router.get("/system/projects")
def system_projects():
    """Project/area entities discovered from the vault (§15, §30).

    Fully data-driven: a new project folder appears here with no code change, which is what
    makes the dashboard's Projects page generic instead of a hardcoded list.
    """
    return gw().projects()
