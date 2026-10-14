"""REST API (§6). FastAPI. Read + benchmark operations only; nothing writes to the vault.

Endpoints that change server state (the /config/* group, plus feedback and benchmark-run) require
`require_local_write` (app/services/security.py, §5.4): loopback client, same-origin Origin/Referer,
and the `X-MG-Token` header. Everything else stays a plain read."""
from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import replace as dc_replace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.adapters.registry import detect_all
from app.benchmark.evaluator import validate_evaluation, validate_label
from app.benchmark.runner import BenchmarkRunner, estimate_plan, load_questions
from app.benchmark.statistics import aggregate_stats
from app.benchmark.timeseries import DEFAULT_MAX_POINTS, MAX_POINTS_CEILING, build_timeseries
from app.core.state import STATE, GatewayNotReady, LegacyStateView
from app.schemas.models import DEFAULT_EXPLICIT_PIPELINE, PIPELINES
from app.services import security
from app.services.envfile import EnvValueError, set_env_var
from app.services.security import (MODEL_KEY_ENV_VARS, get_or_create_local_token, mask_secret,
                                   require_local_write, require_localhost)
from config import local_settings as local_cfg
from config.optional_stages_catalog import CATALOG as OPTIONAL_STAGES_CATALOG
from config.optional_stages_catalog import REJECTED as OPTIONAL_STAGES_REJECTED
from config.retrieval import resolve_vault_path, validate_vault_path_for_runtime

router = APIRouter()
MAX_BENCH_QUESTIONS = 200
MAX_BENCH_UNITS = 2000
Pipeline = Literal[("auto",) + PIPELINES]
BenchPipeline = Literal[PIPELINES]


def gw():
    """Current gateway (ANA-106: state lives in app.core.state.STATE; endpoints may also take
    `Depends(app.api.deps.get_gateway)`, which tests override via `dependency_overrides`)."""
    try:
        return STATE.require_gateway()
    except GatewayNotReady as exc:
        raise HTTPException(503, "gateway não inicializado") from exc


def __getattr__(name: str):  # deprecated alias (ANA-106): use app.core.state.STATE
    if name == "_state":
        import warnings
        warnings.warn("routes." + name + " is deprecated; use app.core.state.STATE",
                      DeprecationWarning, stacklevel=2)
        return LegacyStateView(STATE)
    raise AttributeError(name)


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
    # Who actually called (Hermes, Claude Code, Codex…), distinct from the interface ("rest").
    # Optional; recorded in metrics_json.client and surfaced in GET /benchmark/runs (§5.1).
    client: str | None = Field(None, max_length=200)
    # R3: context (default, unchanged) | answer (router + short cited answer) | delegate (= context for now).
    mode: Literal["context", "answer", "delegate"] = "context"
    risk: Literal["low", "medium", "high"] = "medium"


class RouteRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    task_kind: str = Field("memory", max_length=50)
    risk: Literal["low", "medium", "high"] = "medium"
    context_tokens: int = Field(0, ge=0, le=10_000_000)


class GenerateRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    scope: str | None = Field(None, max_length=500)
    max_results: int = Field(10, ge=1, le=50)
    risk: Literal["low", "medium", "high"] = "medium"
    client: str | None = Field(None, max_length=200)


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

    # ANA-031 / P-09: a hostile or buggy caller cannot queue an unbounded paid run.
    @field_validator("question_ids")
    @classmethod
    def _cap_ids(cls, v):
        if v is not None and len(v) > MAX_BENCH_QUESTIONS:
            raise ValueError(f"no máximo {MAX_BENCH_QUESTIONS} question_ids")
        return v

    @field_validator("questions")
    @classmethod
    def _cap_questions(cls, v):
        if v is not None:
            if len(v) > MAX_BENCH_QUESTIONS:
                raise ValueError(f"no máximo {MAX_BENCH_QUESTIONS} questions")
            if any(len(q) > 2000 for q in v):
                raise ValueError("pergunta com mais de 2000 caracteres")
        return v

    @field_validator("pipelines", "consumers")
    @classmethod
    def _cap_lists(cls, v):
        if v is not None and len(v) > 20:
            raise ValueError("lista longa demais (máx. 20)")
        return v


def _bench_limit(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _check_bench_size(req: "BenchmarkRequest", n_questions: int) -> None:
    """ANA-031: questions x repetitions ceiling (MG_BENCH_MAX_UNITS, default 2000; 0 = off)."""
    cap = _bench_limit("MG_BENCH_MAX_UNITS", MAX_BENCH_UNITS)
    if cap > 0 and n_questions * req.repetitions > cap:
        raise HTTPException(422, f"benchmark grande demais: {n_questions} perguntas x {req.repetitions} "
                                 f"repetições > {cap}")


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


def session_scope(request: Request | None, requested: str | None) -> str | None:
    """ANA-032 / P-05: a request carrying a valid `X-MG-Session` token gets the scope bound to that token
    by the server (the project of the terminal it was minted for); the client-sent `scope` is ignored.
    Without the header (or with an unknown/expired token) nothing changes."""
    if request is None:
        return requested
    from app.services import session_tokens
    bound = session_tokens.resolve(request.headers.get(session_tokens.HEADER))
    return bound if bound else requested


def _search(req: SearchRequest, pipeline: str, request: Request | None = None):
    try:
        r = gw().search(req.query, pipeline, req.max_results,
                        jev_overrides=_overrides(req.jev_mode, req.threshold, req.review_action),
                        context_budget=req.context_budget, scope=session_scope(request, req.scope),
                        run_meta={"kind": "api", "agent": "rest", "client": req.client})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    out = r.to_dict(include_candidates=req.include_candidates)
    if req.mode != "context":   # default path above is byte-for-byte what it was before R3
        from app.routing.answer import apply_mode, merge_mode
        out = merge_mode(out, apply_mode(gw(), r, req.mode, risk=req.risk))
    return out


def _health_warnings(g) -> list[dict]:
    """T0.3: optional stages that are missing are reported, never silent. No network, no subprocess."""
    import os
    import shutil
    out: list[dict] = []
    if g is not None:
        binary = getattr(getattr(g, "graphify", None), "bin", None)
        if binary and not shutil.which(str(binary)) and not os.path.exists(str(binary)):
            out.append({"component": "graphify", "code": "binary_missing",
                        "message": "Graphify not found: graph pipelines degrade; default 'auto' keeps working.",
                        "hint": "Install graphify or ignore: the baseline pipeline does not need it."})
    if not os.getenv("TYPESAFE_API_KEY"):
        out.append({"component": "jev", "code": "api_key_missing",
                    "message": "JEV key not set: JEV pipelines are unavailable; 'auto'/baseline keep working.",
                    "hint": "Set TYPESAFE_API_KEY in .env (each user brings their own key)."})
    return out


@router.get("/health")
def health():
    g = STATE.gateway
    return {"status": "ok" if g else "starting", "vault_exists": bool(g and g.vault.exists()),
            "warnings": _health_warnings(g)}


@router.post("/memory/search")
def memory_search(req: SearchRequest, request: Request):
    return _search(req, req.pipeline, request)


@router.post("/route")
def route_decision(req: RouteRequest):
    """Deterministic RoutingDecision for a query. Read-only: zero model calls, same guard as /memory/search."""
    import dataclasses

    from app.routing.answer import plan_route
    try:
        decision = plan_route(req.query, req.context_tokens, req.task_kind, req.risk)[0]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"router indisponível: {type(exc).__name__}") from exc
    return dataclasses.asdict(decision)


@router.post("/generate", dependencies=[Depends(require_local_write)])
def generate(req: GenerateRequest, request: Request):
    """memory_search mode=answer over REST. Calls a model (may cost money), so it needs the same
    local-write guard (loopback + same-origin + X-MG-Token) as the other state/spend endpoints."""
    return _search(SearchRequest(query=req.query, scope=req.scope, max_results=req.max_results,
                                 client=req.client, mode="answer", risk=req.risk), "auto", request)


@router.post("/memory/search/baseline")
def memory_search_baseline(req: SearchRequest, request: Request):
    return _search(req, "baseline", request)


@router.post("/memory/search/graphify")
def memory_search_graphify(req: SearchRequest, request: Request):
    return _search(req, "graphify", request)


@router.post("/memory/search/graphify-jev")
def memory_search_graphify_jev(req: SearchRequest, request: Request):
    return _search(req, "graphify_jev", request)


def _questions(req: BenchmarkRequest) -> list[dict]:
    if req.questions:
        return [{"id": f"adhoc{i + 1:02d}", "question": q} for i, q in enumerate(req.questions)]
    qs = load_questions(gw().bench_cfg.questions_path)
    if req.question_ids:
        qs = [q for q in qs if q["id"] in set(req.question_ids)]
    return qs


def _sized_questions(req: BenchmarkRequest) -> list[dict]:
    qs = _questions(req)
    _check_bench_size(req, len(qs))   # ANA-031: 422 before anything is queued or paid
    return qs


def _run_benchmark(req: BenchmarkRequest, pipelines):
    runner = BenchmarkRunner(gw())
    qs = _sized_questions(req)
    if not qs:
        raise HTTPException(422, "nenhuma pergunta selecionada")
    kwargs = dict(pipelines=pipelines, consumers=[c.model_dump() for c in req.consumers],
                  repetitions=req.repetitions, warmup=req.warmup, max_results=req.max_results,
                  jev_overrides=_overrides(req.jev_mode, req.threshold), notes=req.notes)
    if not req.background:
        return runner.run(qs, **kwargs)
    job = uuid.uuid4().hex[:8]
    STATE.jobs.create(job)

    def work():
        try:
            runner.progress = lambda e: STATE.jobs.append_progress(
                job, {k: e[k] for k in ("question_id", "pipeline", "run_id")})
            STATE.jobs.update(job, status="done", result=runner.run(qs, **kwargs))
        except Exception as exc:  # noqa: BLE001
            STATE.jobs.update(job, status="error", error=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return {"job_id": job, "status": "running"}


@router.post("/benchmark/run", dependencies=[Depends(require_local_write)])
def benchmark_run(req: BenchmarkRequest):
    return _run_benchmark(req, req.pipelines or [DEFAULT_EXPLICIT_PIPELINE])


@router.post("/benchmark/run-all", dependencies=[Depends(require_local_write)])
def benchmark_run_all(req: BenchmarkRequest):
    return _run_benchmark(req, list(PIPELINES))


@router.post("/benchmark/estimate")
def benchmark_estimate(req: BenchmarkRequest):
    # Average real JEV input tokens per graphify_jev run from history (§82: "quando houver dados suficientes").
    rows = gw().db.query("SELECT metrics_json FROM runs WHERE pipeline='graphify_jev' AND warmup=0 "
                         "ORDER BY created_at DESC LIMIT 200")
    toks = [json.loads(r["metrics_json"]).get("jev_input_tokens") for r in rows if r["metrics_json"]]
    toks = [t for t in toks if t]
    avg = sum(toks) / len(toks) if toks else None
    return estimate_plan(len(_sized_questions(req)), req.pipelines or list(PIPELINES),
                         [c.model_dump() for c in req.consumers], req.repetitions, avg_jev_tokens=avg)


@router.get("/benchmark/jobs/{job_id}")
def benchmark_job(job_id: str):
    j = STATE.jobs.get(job_id)
    if not j:
        raise HTTPException(404, "job não encontrado")
    return j


@router.post("/benchmark/threshold-sweep", dependencies=[Depends(require_local_write)])
def threshold_sweep(req: BenchmarkRequest):
    return BenchmarkRunner(gw()).threshold_sweep(_sized_questions(req))


@router.get("/benchmark/runs")
def benchmark_runs(response: Response, limit: int = 100, offset: int = 0, session_id: str | None = None,
                   agent: str | None = None, q: str | None = None, since: float | None = None,
                   adhoc_only: bool = False, full: bool = False, until: float | None = None):
    """Server-side paginated/filtered run list (§4, §5.1).

    Returns a bare list (never `{runs:[...]}`) so existing frontend callers that do
    `Array.isArray(await api(...))` keep working unchanged. The total count that matches the
    filters (ignoring limit/offset) is exposed via the `X-Total-Count` header for callers that
    want real pagination instead of guessing from `len(page)`.
    """
    db = gw().db
    rows = db.list_runs(limit=limit, offset=offset, session_id=session_id, agent=agent, q=q,
                        since=since, adhoc_only=adhoc_only, full=full, until=until)
    response.headers["X-Total-Count"] = str(db.count_runs(session_id=session_id, agent=agent, q=q,
                                                           since=since, adhoc_only=adhoc_only, until=until))
    return rows


@router.get("/benchmark/runs/{run_id}")
def benchmark_run_detail(run_id: str, request: Request):
    r = gw().db.get_run(run_id)
    if not r:
        raise HTTPException(404, "run não encontrado")
    if not security.is_local_client(request):  # ANA-041: the delivered context never leaves loopback
        r = {k: v for k, v in r.items() if k not in ("context", "answer")}
    return r


@router.get("/benchmark/sessions")
def benchmark_sessions(response: Response, limit: int = Query(50, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Sessions by last activity (newest run first), with first_run_at / last_run_at / runs."""
    db = gw().db
    response.headers["X-Total-Count"] = str(db.count_sessions())
    return db.list_sessions(limit, offset)


@router.get("/benchmark/history/summary")
def benchmark_history_summary():
    """What the history really contains (§35): totals, span, runs per day (local + UTC), malformed timestamps."""
    return gw().db.history_summary()


@router.get("/benchmark/timeseries")
def benchmark_timeseries(metric: str = "tokens", agg: str = "day", since: str | None = None,
                         until: str | None = None, pipeline: str | None = None,
                         max_points: int = Query(DEFAULT_MAX_POINTS, ge=3, le=MAX_POINTS_CEILING),
                         tz: Literal["local", "utc"] = "local"):
    """Series computed on the server over ALL runs in range (no 5000-run ceiling). Points are ASC by
    time; `sampled` is true only when the view had to be downsampled (after sorting) to `max_points`."""
    try:
        return build_timeseries(gw().db.series_rows(pipeline), metric, agg, since, until, max_points,
                                utc=tz == "utc")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/benchmark/stats")
def benchmark_stats(session_id: str | None = None):
    return aggregate_stats(gw().db, session_id)


@router.get("/benchmark/questions")
def benchmark_questions():
    return load_questions(gw().bench_cfg.questions_path)


class FalseNegativeRequest(BaseModel):
    run_id: str
    candidate_id: str


@router.post("/feedback/false-negative", dependencies=[Depends(require_local_write)])
def mark_false_negative(req: FalseNegativeRequest):
    try:
        return gw().db.mark_false_negative(req.run_id, req.candidate_id)
    except KeyError as exc:
        raise HTTPException(404, f"não encontrado: {exc}") from exc


class LabelRequest(BaseModel):
    run_id: str
    source_file: str
    label: str


@router.post("/feedback/label", dependencies=[Depends(require_local_write)])
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


@router.post("/feedback/evaluation", dependencies=[Depends(require_local_write)])
def add_evaluation(req: EvaluationRequest):
    gw().db.add_evaluation(validate_evaluation(req.model_dump()))
    return {"ok": True}


def _settings_section(g) -> dict:
    """`settings` block for GET /system/info (§3): every value the config page can change, read
    back live so a caller can confirm a write took effect without restarting the server."""
    return {
        "verdict_enabled": g.optimizer.cfg.verdict_enabled,
        "optional_stages": local_cfg.get_optional_stages(),
        "vault_path": str(g.vault.root),
        "keys_present": {k: mask_secret(os.environ.get(k)) for k in MODEL_KEY_ENV_VARS},
    }


@router.get("/system/info")
def system_info(request: Request):
    g = gw()
    info = g.system_info()
    info["settings"] = _settings_section(g)
    from app.services import hardening  # ANA-045: no absolute paths for non-loopback clients
    if hardening.should_redact_paths(security.is_local_client(request)):
        info = hardening.redact_info(info, str(g.vault.root))
    return info


@router.get("/system/integrations")
def integrations(refresh: bool = False):
    return detect_all(refresh)


@router.get("/system/memory")
def system_memory(inactive_days: int = 90, hot_min: int = 5):
    """Read-only inventory of the persistent memory (app/services/memory_audit.py).

    Counts only — never note content. It audits the vault the RUNNING gateway was built against,
    not a path resolved from the environment, so the numbers always describe the same corpus the
    answers come from. hot/warm/cold come from the gateway's own benchmark.db, which the auditor
    re-opens with `mode=ro` (see `delivery_counts`).
    """
    from app.services.memory_audit import MemoryAuditor
    g = gw()
    report = MemoryAuditor(g.vault.root, db_path=g.db.path,
                           excluded_dirs=g.retrieval_cfg.excluded_dirs).audit(
        inactive_days=max(1, min(int(inactive_days), 3650)), hot_min=max(1, int(hot_min)))
    return report.counts_only()


@router.get("/system/projects")
def system_projects():
    """Project/area entities discovered from the vault (§15, §30).

    Fully data-driven: a new project folder appears here with no code change, which is what
    makes the dashboard's Projects page generic instead of a hardcoded list.
    """
    return gw().projects()


# ---------------------------------------------------------------------------------------------
# /config/* — interactive configuration page (§3). Every POST here requires require_local_write
# (loopback + same-origin + X-MG-Token); GETs that only reveal masked/boolean state stay open to
# any local caller EXCEPT the token bootstrap itself, which is loopback-only (require_localhost).
# ---------------------------------------------------------------------------------------------

@router.get("/config/token", dependencies=[Depends(require_localhost)])
def config_token(request: Request):
    """One-time bootstrap: the frontend fetches this once and attaches it to every write call."""
    from app.services import ui_challenge  # ANA-040: MG_TOKEN_COOKIE=warn|enforce|off
    if not ui_challenge.check_token_bootstrap(request):
        raise HTTPException(status_code=403, detail="ui challenge required")
    return {"token": get_or_create_local_token()}


@router.get("/config/shell-confirm", dependencies=[Depends(require_localhost)])
def config_shell_confirm(request: Request):
    """ANA-042: value for the X-MG-Confirm header; only the UI (holding the HttpOnly cookie) gets it."""
    from app.services import ui_challenge
    if not ui_challenge.has_ui_cookie(request):
        raise HTTPException(status_code=403, detail="ui challenge required")
    return {"confirm": ui_challenge.ui_cookie_value()}


@router.get("/config/model-keys", dependencies=[Depends(require_localhost)])
def get_model_keys():
    """Masked (last 4 chars) view of every model/consumer secret this page can set. Never the
    plaintext value — that never round-trips back to the client after being saved."""
    return {k: mask_secret(os.environ.get(k)) for k in MODEL_KEY_ENV_VARS}


class ModelKeyRequest(BaseModel):
    key_name: str = Field(..., description=f"um de {MODEL_KEY_ENV_VARS}")
    value: str = Field(..., min_length=1, max_length=2000)


@router.post("/config/model-key", dependencies=[Depends(require_local_write)])
def set_model_key(req: ModelKeyRequest):
    if req.key_name not in MODEL_KEY_ENV_VARS:
        raise HTTPException(422, f"key_name inválido: {req.key_name!r}. Use um de {MODEL_KEY_ENV_VARS}")
    # Never logged: no logger call anywhere in this path touches req.value.
    try:
        set_env_var(security.ENV_PATH, req.key_name, req.value)  # ANA-006: validates before writing
    except EnvValueError as exc:
        raise HTTPException(422, str(exc)) from None
    os.environ[req.key_name] = req.value
    return {"key_name": req.key_name, "masked": mask_secret(req.value)}


class VaultPathRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)


@router.post("/config/vault-path", dependencies=[Depends(require_local_write)])
def set_vault_path(req: VaultPathRequest):
    from app.gateway.memory_gateway import MemoryGateway

    old = gw()
    try:
        candidate = resolve_vault_path(req.path)
        validated = validate_vault_path_for_runtime(candidate, db_path=old.db.path)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    set_env_var(security.ENV_PATH, "MEMORY_GATEWAY_VAULT", str(validated))
    os.environ["MEMORY_GATEWAY_VAULT"] = str(validated)
    # Rebuild against the SAME db/jev/optimizer config the running gateway already had -- only
    # vault_path changes. Reusing `old.db` (instead of opening a second connection to the same
    # file) and `old._jev_backend` is also what keeps a test-injected fake judge working across a
    # vault switch, and preserves any runtime toggle already applied (e.g. verdict_enabled).
    new_retrieval_cfg = dc_replace(old.retrieval_cfg, vault_path=validated)
    try:
        new_gw = MemoryGateway(retrieval_cfg=new_retrieval_cfg, jev_cfg=old.jev_cfg, bench_cfg=old.bench_cfg,
                               db=old.db, jev_backend=old._jev_backend, opt_cfg=old.opt_cfg,
                               optimizer_cfg=old.optimizer.cfg)
        from app.memory_store.index import attach_saved_context  # ANA-078: keep saved notes after a vault switch
        attach_saved_context(new_gw)
        new_gw.warm()
    except Exception as exc:  # noqa: BLE001 -- a bad rebuild must not brick the running server
        raise HTTPException(422, f"falha ao reapontar o gateway: {exc}") from exc
    STATE.gateway = new_gw
    return {"vault_path": str(validated), "markdown_files": len(new_gw.vault.list_markdown())}


class VaultScaffoldRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1000)
    dry_run: bool = False
    project: str | None = Field(None, max_length=120)


@router.post("/config/vault-scaffold", dependencies=[Depends(require_local_write)])
def vault_scaffold(req: VaultScaffoldRequest):
    """Create the standard memory folder layout in the chosen vault. Only adds missing folders/templates."""
    from app.memory_store import vault_scaffold as vs
    try:
        root = validate_vault_path_for_runtime(resolve_vault_path(req.path), db_path=gw().db.path)
        out = vs.scaffold(root, dry_run=req.dry_run)
        if req.project:
            out["project"] = vs.scaffold_project(root, req.project, dry_run=req.dry_run)["created"]
        return out
    except (FileNotFoundError, NotADirectoryError, PermissionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/config/verdict")
def get_verdict_flag():
    return {"enabled": gw().optimizer.cfg.verdict_enabled}


class VerdictRequest(BaseModel):
    enabled: bool


@router.post("/config/verdict", dependencies=[Depends(require_local_write)])
def set_verdict_flag(req: VerdictRequest):
    g = gw()
    local_cfg.update(verdict_enabled=req.enabled)
    g.optimizer.cfg.verdict_enabled = req.enabled  # reflects immediately, no restart (§3)
    return {"enabled": req.enabled}


@router.get("/config/optional-stages")
def get_optional_stages_config():
    return {
        "catalog": OPTIONAL_STAGES_CATALOG,
        "rejected": OPTIONAL_STAGES_REJECTED,
        "enabled": local_cfg.get_optional_stages(),
    }


class OptionalStagesRequest(BaseModel):
    stages: dict[str, bool]


@router.post("/config/optional-stages", dependencies=[Depends(require_local_write)])
def set_optional_stages_config(req: OptionalStagesRequest):
    unknown = sorted(set(req.stages) - set(OPTIONAL_STAGES_CATALOG))
    if unknown:
        raise HTTPException(422, f"estágio(s) desconhecido(s): {', '.join(unknown)}")
    updated = local_cfg.update(optional_stages=req.stages)
    return {"enabled": updated.get("optional_stages", {})}
