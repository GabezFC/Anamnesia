"""R6: routing benchmark harness (STATIC_CHEAP / STATIC_DEFAULT / STATIC_STRONG / DYNAMIC_ROUTER / ORACLE).

Execution goes through an injected `ModelRunner(task, model_entry) -> RunOutcome`:
  * tests and the default CLI use `StubRunner` (deterministic, SIMULATED: numbers are NOT evidence);
  * `RealRunner` calls app/adapters/models and is only built when a model is usable and `--real` is passed.
A `ResultCache` guarantees each (task x model) is executed once; ORACLE is computed from those cached cells.
Pure orchestration: this module never opens the real benchmark.db (a Database is only used if passed in).
"""
from __future__ import annotations

import hashlib
import json
import random
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from app.routing import metrics as M
from app.routing.escalation import next_model
from app.routing.policy import preset
from app.routing.registry import ModelEntry, Registry
from app.routing.router import route
from app.routing.tasks import DIFFICULTIES, Task
from app.routing.verifiers import (VerifyLevel, VerifyResult, normalize, verify_abstention, verify_fact_match,
                                   verify_json_schema)

STATIC_CHEAP, STATIC_DEFAULT, STATIC_STRONG = "STATIC_CHEAP", "STATIC_DEFAULT", "STATIC_STRONG"
DYNAMIC_ROUTER, ORACLE = "DYNAMIC_ROUTER", "ORACLE"
ALL_STRATEGIES = (STATIC_CHEAP, STATIC_DEFAULT, STATIC_STRONG, DYNAMIC_ROUTER, ORACLE)
STUB_BANNER = "SIMULATED (stub runner): numbers are NOT evidence"
PROMPT_VERSION = "rb1"


# ------------------------------------------------------------------ outcome + runners
@dataclass
class RunOutcome:
    answer: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: float | None = None
    error: str | None = None
    simulated: bool = False


ModelRunner = Callable[[Task, ModelEntry], RunOutcome]


def build_prompt(task: Task) -> str:
    """Same prompt for every model (spec §23). Self-contained: no retrieved context is injected here."""
    if task.kind == "extraction":
        return task.query + "\nResponda APENAS com o JSON, sem texto adicional."
    return task.query + "\nResponda de forma curta e objetiva. Se a informação não existir, diga que não existe."


def is_self_contained(task: Task) -> bool:
    """Tasks answerable from the prompt alone. memory_qa needs retrieved context, which this harness does not inject."""
    return task.kind == "extraction"


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


class StubRunner:
    """Deterministic fake model. P(solve) grows with tier and falls with difficulty. SIMULATED."""
    P = {"easy": (0.55, 0.9, 0.97), "medium": (0.25, 0.6, 0.9), "hard": (0.05, 0.35, 0.75)}
    simulated = True

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.calls = 0

    def _p(self, task: Task, entry: ModelEntry) -> float:
        row = self.P[task.difficulty_label]
        return row[min(max(entry.tier, 1), 3) - 1]

    def __call__(self, task: Task, entry: ModelEntry) -> RunOutcome:
        self.calls += 1
        solved = (_h(self.seed, task.id, entry.id) % 10_000) / 10_000 < self._p(task, entry)
        gt, v = task.ground_truth, task.verifier
        if not solved:
            ans = "Não sei responder com certeza." if v.get("type") == "abstention" else "resposta incorreta"
            if v.get("type") == "json_schema":
                ans = '{"path": "x", "token": "y"}'
        elif v.get("type") == "json_schema":
            ans = json.dumps(gt.get("expected_json", {}), ensure_ascii=False)
        elif v.get("type") == "abstention":
            ans = "Não existe informação sobre isso."
        else:
            ans = " ".join(gt.get("expected_facts", [])) or "ok"
        t_in = max(1, len(build_prompt(task)) // 4)
        return RunOutcome(ans, t_in, max(1, len(ans) // 4), latency_ms=float(5 * entry.tier), simulated=True)


class RealRunner:
    """Calls app/adapters/models through make_adapter. temperature 0, per-call cap `timeout_s`."""

    def __init__(self, avail: dict | None = None, timeout_s: float = 120.0, max_tokens: int = 400):
        self.avail, self.timeout_s, self.max_tokens = avail, timeout_s, max_tokens
        self._adapters: dict[str, Any] = {}

    def _adapter(self, entry: ModelEntry):
        if entry.id not in self._adapters:
            from app.routing.answer import make_adapter
            a = make_adapter(entry, self.avail)
            if hasattr(a, "timeout_s"):
                a.timeout_s = self.timeout_s
            self._adapters[entry.id] = a
        return self._adapters[entry.id]

    def __call__(self, task: Task, entry: ModelEntry) -> RunOutcome:
        r = self._adapter(entry).generate(build_prompt(task), temperature=0.0, max_tokens=self.max_tokens)
        return RunOutcome(r.answer, r.input_tokens, r.output_tokens, r.latency_ms, r.error, simulated=False)


# ------------------------------------------------------------------ cache
class ResultCache:
    """(task_id, model_id) -> RunOutcome; each cell executes once. Optional JSON persistence."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.cells: dict[str, RunOutcome] = {}
        self.executions = 0
        self.hits = 0
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.cells = {k: RunOutcome(**v) for k, v in raw.items()}

    @staticmethod
    def key(task_id: str, model_id: str) -> str:
        return f"{PROMPT_VERSION}|{task_id}|{model_id}"

    def get_or_run(self, task: Task, entry: ModelEntry, runner: ModelRunner) -> RunOutcome:
        k = self.key(task.id, entry.id)
        if k in self.cells:
            self.hits += 1
            return self.cells[k]
        out = runner(task, entry)
        self.executions += 1
        self.cells[k] = out
        return out

    def peek(self, task_id: str, model_id: str) -> RunOutcome | None:
        return self.cells.get(self.key(task_id, model_id))

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({k: asdict(v) for k, v in self.cells.items()}, ensure_ascii=False),
                                 encoding="utf-8")


# ------------------------------------------------------------------ scoring (objective verifiers only)
def _extract_json(text: str):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[4:] if t.lower().startswith("json") else t
    a, b = t.find("{"), t.rfind("}")
    return t[a:b + 1] if a != -1 and b > a else t


def verify_task(task: Task, answer: str | None) -> VerifyResult:
    """The objective success check of docs/ROUTING_SUCCESS_DEFINITION.md (citation check needs retrieval: skipped)."""
    v, gt = task.verifier, task.ground_truth
    kind = v.get("type")
    if answer is None:
        return VerifyResult(False, VerifyLevel.LIGHT, "no_answer")
    if kind == "json_schema":
        raw = _extract_json(answer)
        res = verify_json_schema(raw, v.get("schema", {}))
        if not res.passed or not v.get("match_expected"):
            return res
        got = json.loads(raw)
        exp = gt.get("expected_json", {})
        bad = [k for k, val in exp.items() if normalize(str(got.get(k, ""))) != normalize(str(val))]
        return res if not bad else VerifyResult(False, res.level, "value_mismatch", {"fields": bad})
    if kind == "abstention":
        return verify_abstention(answer)
    return verify_fact_match(answer, gt.get("expected_facts", []))


# ------------------------------------------------------------------ cost helpers
def call_cost(entry: ModelEntry, out: RunOutcome) -> tuple[float | None, str]:
    """(cost, origin). None when the price is unavailable; never 0 for a missing price."""
    rates = entry.cost_per_mtok()
    if rates is None:
        return None, "unavailable"
    if rates["input"] == 0 and rates["output"] == 0:
        return 0.0, "estimated" if out.simulated else "measured"
    if out.input_tokens is None or out.output_tokens is None:
        return None, "unavailable"
    c = (out.input_tokens * rates["input"] + out.output_tokens * rates["output"]) / 1e6
    return c, "estimated" if out.simulated else "measured"


def _tok(out: RunOutcome) -> int | None:
    return None if out.input_tokens is None or out.output_tokens is None else out.input_tokens + out.output_tokens


def _sum_or_none(vals):
    return None if any(v is None for v in vals) else float(sum(vals))


# ------------------------------------------------------------------ model selection
def cheapest(models: Sequence[ModelEntry]) -> ModelEntry:
    return min(models, key=lambda m: (m.tier, m._sort_cost(), m.id))


def strongest(models: Sequence[ModelEntry]) -> ModelEntry:
    top = max(m.tier for m in models)
    return min((m for m in models if m.tier == top), key=lambda m: (m._sort_cost(), m.id))


def default_model(models: Sequence[ModelEntry], default_id: str | None = None) -> ModelEntry:
    """Configured default; otherwise cheapest model of the middle tier present (documented assumption)."""
    if default_id:
        for m in models:
            if m.id == default_id:
                return m
    tiers = sorted({m.tier for m in models})
    return cheapest([m for m in models if m.tier == tiers[len(tiers) // 2]])


def sample_tasks(tasks: Sequence[Task], n: int | None, seed: int = 42) -> list[Task]:
    """Deterministic sample, stratified by difficulty (proportional, remainder to larger strata)."""
    tasks = sorted(tasks, key=lambda t: t.id)
    if n is None or n >= len(tasks):
        return list(tasks)
    rng = random.Random(seed)
    by: dict[str, list[Task]] = defaultdict(list)
    for t in tasks:
        by[t.difficulty_label].append(t)
    for v in by.values():
        rng.shuffle(v)
    quotas = {d: int(n * len(by[d]) / len(tasks)) for d in by}
    rest = n - sum(quotas.values())
    for d in sorted(by, key=lambda d: (-len(by[d]), d)):
        if rest <= 0:
            break
        if quotas[d] < len(by[d]):
            quotas[d] += 1
            rest -= 1
    out = [t for d in by for t in by[d][:quotas[d]]]
    return sorted(out, key=lambda t: t.id)


# ------------------------------------------------------------------ harness
@dataclass
class BenchResult:
    records: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)       # run_id-less side data (decisions, verifications) by record key
    meta: dict = field(default_factory=dict)


def _base_record(task: Task, strategy: str, simulated: bool) -> dict:
    return {"task_id": task.id, "kind": task.kind, "difficulty": task.difficulty_label, "strategy": strategy,
            "risk": task.risk, "simulated": simulated, "retry_count": 0, "retry_cost": 0.0,
            "router_cost": 0.0, "router_tokens": 0, "verify_cost": 0.0, "verify_tokens": 0,
            "router_latency_ms": None, "t_star": None, "oracle_cost": None, "penalty_cost": None}


def run_static(task: Task, entry: ModelEntry, strategy: str, cache: ResultCache, runner: ModelRunner) -> dict:
    out = cache.get_or_run(task, entry, runner)
    res = verify_task(task, out.answer)
    cost, origin = call_cost(entry, out)
    r = _base_record(task, strategy, out.simulated)
    r.update(solved=bool(res.passed), cost=cost, final_cost=cost, cost_origin=origin, tokens=_tok(out),
             tokens_origin="estimated" if out.simulated else "measured", initial_model=entry.id, final_model=entry.id,
             initial_tier=entry.tier, final_tier=entry.tier, escalation_count=0, failure_code=res.failure_code,
             latency_ms=out.latency_ms, verify_level="NONE")
    r["_attempts"] = [(entry.id, bool(res.passed), res.failure_code)]
    return r


def run_dynamic(task: Task, registry: Registry, policy, cache: ResultCache, runner: ModelRunner,
                strategy: str = DYNAMIC_ROUTER) -> dict:
    t0 = time.perf_counter()
    dec = route(task.query, 0, "memory", task.risk, registry, policy)   # no retrieved context is injected here -> 0
    router_ms = round((time.perf_counter() - t0) * 1000, 3)
    r = _base_record(task, strategy, bool(getattr(runner, "simulated", False)))
    r.update(router_latency_ms=router_ms, router_tokens=dec.router_tokens, complexity=dec.difficulty,
             verify_level=dec.verify, reason_codes=list(dec.reason_codes), policy_version=dec.policy_version,
             registry_version=dec.registry_version, effort=dec.effort, _decision=dec)
    if dec.model_id is None:
        r.update(solved=False, cost=0.0, final_cost=0.0, cost_origin="measured", tokens=0, tokens_origin="measured",
                 initial_model=None, final_model=None, initial_tier=None, final_tier=None, escalation_count=0,
                 failure_code="routing_miss", latency_ms=None, _attempts=[])
        return r
    attempts, costs, origins, toks, sims = [], [], [], [], []
    model_id, failed, res, last_out = dec.model_id, 0, None, None
    while True:
        entry = registry.get(model_id)
        out = cache.get_or_run(task, entry, runner)
        res = verify_task(task, out.answer)
        c, o = call_cost(entry, out)
        costs.append(c), origins.append(o), toks.append(_tok(out)), sims.append(out.simulated)
        attempts.append((entry.id, bool(res.passed), res.failure_code))
        last_out, last_entry = out, entry
        # LIGHT/FULL verification gates escalation; NONE trusts the first answer (no escalation possible).
        if res.passed or dec.verify == "NONE":
            break
        failed += 1
        nxt = next_model(dec, failed)
        if nxt is None:
            break
        model_id = nxt
    total = _sum_or_none(costs)
    r.update(solved=bool(res.passed), cost=total, final_cost=costs[-1],
             retry_cost=_sum_or_none(costs[:-1]) if len(costs) > 1 else 0.0,
             cost_origin=M.combine_origin(origins), tokens=_sum_or_none(toks), tokens_origin="estimated" if any(sims) else "measured",
             initial_model=dec.model_id, final_model=last_entry.id, initial_tier=dec.tier, final_tier=last_entry.tier,
             escalation_count=len(attempts) - 1, failure_code=res.failure_code, latency_ms=last_out.latency_ms,
             simulated=any(sims), _attempts=attempts)
    if r["tokens"] is not None:
        r["tokens"] = int(r["tokens"])
    return r


def oracle_cells(task: Task, models: Sequence[ModelEntry], cache: ResultCache, runner: ModelRunner) -> dict:
    cells = {}
    for m in models:
        out = cache.get_or_run(task, m, runner)
        c, o = call_cost(m, out)
        cells[m.id] = {"tier": m.tier, "solved": bool(verify_task(task, out.answer).passed), "cost": c,
                       "origin": o, "tokens": _tok(out), "simulated": out.simulated}
    return cells


def run_oracle(task: Task, cells: dict) -> dict:
    orc = M.oracle_for_task(cells)
    sim = any(c["simulated"] for c in cells.values())
    r = _base_record(task, ORACLE, sim)
    if orc is None:   # nobody solves it: an oracle would not overspend -> cheapest model's cost, unsolved
        cm = min(cells, key=lambda k: (cells[k]["tier"], k))
        r.update(solved=False, cost=cells[cm]["cost"], final_cost=cells[cm]["cost"], initial_model=cm, final_model=cm,
                 initial_tier=cells[cm]["tier"], final_tier=cells[cm]["tier"], tokens=cells[cm]["tokens"],
                 cost_origin=cells[cm]["origin"], failure_code="unsolvable_by_any_model")
    else:
        c = cells[orc["model"]]
        r.update(solved=True, cost=orc["cost"], final_cost=orc["cost"], initial_model=orc["model"],
                 final_model=orc["model"], initial_tier=orc["tier"], final_tier=orc["tier"], tokens=c["tokens"],
                 cost_origin=c["origin"], failure_code=None, t_star=orc["t_star"])
    r.update(tokens_origin="estimated" if sim else "measured", escalation_count=0, latency_ms=None, verify_level="NONE")
    r["_attempts"] = []
    return r


def run_benchmark(tasks: Sequence[Task], models: Sequence[ModelEntry], runner: ModelRunner,
                  strategies: Sequence[str] = ALL_STRATEGIES, policies: Sequence[str] = ("balanced",),
                  default_id: str | None = None, cache: ResultCache | None = None) -> BenchResult:
    """strategies: subset of ALL_STRATEGIES. DYNAMIC_ROUTER runs once per policy preset (strategy name
    DYNAMIC_ROUTER for the first, DYNAMIC_ROUTER:<preset> for the others). ORACLE executes every model on every
    task (through the cache) and annotates every record with t*, oracle cost and the failure penalty."""
    cache = cache or ResultCache()
    models = list(models)
    if not models:
        raise ValueError("no models to benchmark")
    registry = Registry(models=models, file_hash="bench-" + hashlib.sha256(
        ",".join(sorted(m.id for m in models)).encode()).hexdigest()[:12], version="bench")
    chosen = {STATIC_CHEAP: cheapest(models), STATIC_DEFAULT: default_model(models, default_id),
              STATIC_STRONG: strongest(models)}
    records: list[dict] = []
    for t in sorted(tasks, key=lambda t: t.id):
        for s in strategies:
            if s in chosen:
                records.append(run_static(t, chosen[s], s, cache, runner))
            elif s == DYNAMIC_ROUTER:
                for i, p in enumerate(policies):
                    records.append(run_dynamic(t, registry, preset(p, enabled=True), cache, runner,
                                               DYNAMIC_ROUTER if i == 0 else f"{DYNAMIC_ROUTER}:{p}"))
    if ORACLE in strategies:
        by_task: dict[str, dict] = {}
        top = strongest(models)
        for t in sorted(tasks, key=lambda t: t.id):
            by_task[t.id] = oracle_cells(t, models, cache, runner)
            records.append(run_oracle(t, by_task[t.id]))
        for r in records:     # annotate with t*, oracle cost, redo penalty (cost of the strongest model)
            cells = by_task[r["task_id"]]
            orc = M.oracle_for_task(cells)
            r["t_star"] = orc["t_star"] if orc else None
            r["oracle_cost"] = orc["cost"] if orc else None
            r["penalty_cost"] = cells[top.id]["cost"]
    for r in records:
        r.pop("_decision", None)
    cache.save()
    meta = {"models": [{"id": m.id, "tier": m.tier, "provider": m.provider, "price_status": m.price_status} for m in models],
            "chosen": {k: v.id for k, v in chosen.items()}, "strategies": list(strategies), "policies": list(policies),
            "n_tasks": len({r["task_id"] for r in records}), "executions": cache.executions, "cache_hits": cache.hits,
            "registry_version": registry.version_hash(),
            "simulated": any(r["simulated"] for r in records)}
    return BenchResult(records, {}, meta)


# ------------------------------------------------------------------ persistence (only into a DB the caller passes)
def persist(db, result: BenchResult, session_id: str | None = None) -> list[str]:
    """Write records to runs + routing_decisions + verification_results of the GIVEN db. Returns run ids."""
    sid = session_id or f"routing-{int(time.time())}"
    ids = []
    for i, r in enumerate(result.records):
        rid = f"{sid}-{i:05d}-{uuid.uuid4().hex[:6]}"
        clean = {k: v for k, v in r.items() if not k.startswith("_")}
        db.save_run({"run_id": rid, "session_id": sid, "created_at": time.time() + i * 1e-3, "question_id": r["task_id"],
                     "query": r["task_id"], "pipeline": f"routing:{r['strategy']}", "model": r.get("final_model"),
                     "metrics_json": {"routing_record": clean}, "project": "routing-benchmark",
                     "initial_model": r.get("initial_model"), "final_model": r.get("final_model"),
                     "escalation_count": r.get("escalation_count"), "retry_count": r.get("retry_count"),
                     "routing_strategy": r["strategy"]})
        if r["strategy"].startswith(DYNAMIC_ROUTER):
            db.insert_routing_decision(rid, {"policy_version": r.get("policy_version"),
                                             "registry_version": r.get("registry_version"), "complexity": r.get("complexity"),
                                             "risk": r.get("risk"), "tier": r.get("initial_tier"), "model": r.get("initial_model"),
                                             "effort": r.get("effort"), "verify": r.get("verify_level"),
                                             "reason_codes": r.get("reason_codes"), "router_tokens": r.get("router_tokens"),
                                             "router_cost": r.get("router_cost"), "latency_ms": r.get("router_latency_ms")})
            for n, (_m, ok, code) in enumerate(r.get("_attempts", []), 1):
                if r.get("verify_level") != "NONE":
                    db.insert_verification_result(rid, n, r.get("verify_level"), ok, 0, 0.0, code)
        ids.append(rid)
    return ids


def records_from_db(db) -> list[dict]:
    out = []
    for row in db.routing_runs():
        try:
            m = json.loads(row.get("metrics_json") or "{}")
        except ValueError:
            continue
        rec = (m or {}).get("routing_record")
        if isinstance(rec, dict) and "strategy" in rec and "task_id" in rec:
            out.append(rec)
    return out


# ------------------------------------------------------------------ the 12 questions (spec §65): data only
NO_DATA = "sem dados"


def _fmt(lvv: dict | None, unit: str = "") -> str:
    if not lvv or lvv.get("value") is None:
        return NO_DATA
    return f"{lvv['value']}{unit} ({M.ORIGIN_PT.get(lvv['origin'], lvv['origin'])})"


def answer_questions(records: Sequence[dict]) -> list[tuple[str, str]]:
    """Answers come ONLY from non-simulated records; otherwise 'sem dados'."""
    qs = ["O Dynamic Router economizou tokens?", "O Dynamic Router economizou dinheiro?",
          "Quanto custou o próprio router?", "Quanto custou a verificação?",
          "Quantas tarefas precisaram de escalation?", "Quantas tarefas foram over-routed?",
          "Quantas foram under-routed?", "O custo por tarefa resolvida melhorou?", "A qualidade mudou?",
          "Em quais categorias o routing funciona melhor?", "Em quais categorias ele piora?",
          "Qual política/threshold apresentou melhor resultado?"]
    real = [r for r in records if not r.get("simulated")]
    by_s: dict = defaultdict(list)
    for r in real:
        by_s[r["strategy"]].append(r)
    dyn = by_s.get(DYNAMIC_ROUTER, [])
    base = by_s.get(STATIC_DEFAULT, [])
    nd = [NO_DATA] * 12
    if not dyn:
        return list(zip(qs, nd))
    ans = list(nd)
    ids = {r["task_id"] for r in dyn} & {r["task_id"] for r in base}
    dyn_t = [r for r in dyn if r["task_id"] in ids]
    base_t = [r for r in base if r["task_id"] in ids]
    be = M.break_even(dyn, base) if base else None
    esc = sum(1 for r in dyn if (r.get("escalation_count") or 0) > 0)
    ans[4] = f"{esc} de {len(dyn)} tarefas (medido)"
    if base:
        td, tb = M.total_tokens(dyn_t)["value"], M.total_tokens(base_t)["value"]
        if td is not None and tb:
            ans[0] = f"{'SIM' if td < tb else 'NÃO'}: {td} vs {tb} tokens ({(tb - td) / tb * 100:.1f}% de redução vs STATIC_DEFAULT)"
        if be and be["net_savings"]["value"] is not None:
            ans[1] = (f"{'SIM' if be['net_savings']['value'] > 0 else 'NÃO'}: economia líquida {_fmt(be['net_savings'], ' USD')}"
                      f" = {_fmt(be['net_savings_percent'], '%')} vs STATIC_DEFAULT; "
                      f"paga o próprio custo: {M.verdict(be)['value']}")
        else:
            ans[1] = "sem dados (preço indisponível para algum modelo)"
        if be:
            ans[2] = f"{_fmt(be['routing_overhead'], ' USD')}; router determinístico sem chamada de modelo (0 tokens); latência média " + (
                f"{sum(r['router_latency_ms'] for r in dyn) / len(dyn):.3f} ms (medido)" if all(
                    r.get("router_latency_ms") is not None for r in dyn) else NO_DATA)
            ans[3] = f"{_fmt(be['verification_overhead'], ' USD')} (verificadores sem LLM; custo de tokens zero)"
        cd, cb = M.cost_per_solved_task(dyn_t), M.cost_per_solved_task(base_t)
        if cd["value"] is not None and cb["value"] is not None:
            ans[7] = f"{'SIM' if cd['value'] < cb['value'] else 'NÃO'}: {cd['value']} vs {cb['value']} USD/resolvida"
        if be:
            qd = be["quality_delta"]["value"]
            ans[8] = NO_DATA if qd is None else f"variação na taxa de resolução vs STATIC_DEFAULT: {qd:+.3f} (medido)"
        gk = M.group_compare(dyn, base, "kind")
        gd = M.group_compare(dyn, base, "difficulty")
        grp = {f"kind={k}": v for k, v in gk.items()} | {f"difficulty={k}": v for k, v in gd.items()}
        win = sorted(k for k, v in grp.items() if (v["net_savings"]["value"] or 0) > 0)
        lose = sorted(k for k, v in grp.items() if v["net_savings"]["value"] is not None and v["net_savings"]["value"] < 0)
        known = [k for k, v in grp.items() if v["net_savings"]["value"] is not None]
        if known:
            ans[9] = ", ".join(win) or "nenhuma categoria com economia líquida"
            ans[10] = ", ".join(lose) or "nenhuma categoria com piora de custo"
    cl = M.routing_classification(dyn)
    if cl["judged"]:
        ans[5] = f"{cl['over_routed']} de {cl['judged']} ({_fmt(cl['over_rate'])})"
        ans[6] = f"{cl['under_routed']} de {cl['judged']} ({_fmt(cl['under_rate'])})"
    pols = sorted(k for k in by_s if k.startswith(DYNAMIC_ROUTER))
    if len(pols) >= 2 and base:
        scored = []
        for k in pols:
            b = M.break_even(by_s[k], base)
            if b["net_savings"]["value"] is not None and (b["quality_delta"]["value"] or 0) >= 0:
                scored.append((b["net_savings"]["value"], k))
        if scored:
            ans[11] = max(scored)[1] + " (maior economia líquida sem queda de qualidade)"
    else:
        ans[11] = NO_DATA + " (menos de duas políticas executadas)"
    return list(zip(qs, ans))


def _table(summary: dict) -> list[str]:
    lines = ["| Estratégia | N | resolvidas | taxa | custo total | custo/resolvida | tokens/resolvida | escalation |",
             "|---|---|---|---|---|---|---|---|"]
    for s, v in summary["strategies"].items():
        lines.append(f"| {s} | {v['n']} | {v['solved']} | {_fmt(v['success_rate'])} | {_fmt(v['total_cost'], ' USD')} | "
                     f"{_fmt(v['cost_per_solved_task'], ' USD')} | {_fmt(v['tokens_per_solved_task'])} | {_fmt(v['escalation_rate'])} |")
    return lines


def render_report(result: BenchResult, date: str, real_mode: bool, notes: Sequence[str] = ()) -> str:
    records = result.records
    meta = result.meta
    sim = [r for r in records if r.get("simulated")]
    L = [f"# Benchmark de Model Routing — {date}", ""]
    if not real_mode or meta.get("simulated"):
        L += [f"> **{STUB_BANNER}**", ">",
              "> Runner determinístico (stub). Nada abaixo mede modelos reais; as respostas às 12 perguntas ficam 'sem dados'.", ""]
    else:
        L += ["> Execução REAL com modelos locais/configurados (temperatura 0). Amostra pequena: indicativa, não conclusiva.", ""]
    L += ["## Configuração",
          f"- tarefas: {meta['n_tasks']} · estratégias: {', '.join(meta['strategies'])} · políticas: {', '.join(meta['policies'])}",
          f"- modelos: " + ", ".join(f"{m['id']}(tier {m['tier']}, preço {m['price_status']})" for m in meta["models"]),
          f"- baselines escolhidos: {json.dumps(meta['chosen'])}",
          f"- execuções de modelo: {meta['executions']} · acertos de cache: {meta['cache_hits']} (cada tarefa×modelo roda 1×)",
          f"- registry_version: `{meta['registry_version']}`", ""]
    for n in notes:
        L.append(f"- {n}")
    L += ["", "## As 12 perguntas (§65) — só com dados", ""]
    for i, (q, a) in enumerate(answer_questions(records), 1):
        L.append(f"{i}. **{q}** {a}")
    summ = M.build_summary(records)
    if summ["has_data"]:
        L += ["", "## Resultados por estratégia (não simulados)", ""] + _table(summ)
        be = summ.get("break_even")
        if be:
            L += ["", "## Break-even (DYNAMIC_ROUTER vs STATIC_DEFAULT)", "",
                  f"- economia de modelo: {_fmt(be['model_savings'], ' USD')}",
                  f"- overhead router: {_fmt(be['routing_overhead'], ' USD')} · verificação: {_fmt(be['verification_overhead'], ' USD')}"
                  f" · retry/escalonamento: {_fmt(be['retry_overhead'], ' USD')}",
                  f"- economia líquida: {_fmt(be['net_savings'], ' USD')} · paga o próprio custo: **{summ['verdict']['value']}** "
                  f"({summ['verdict']['reason']})"]
    elif sim:
        sm = M.build_summary([dict(r, simulated=False) for r in sim])
        L += ["", "## Mecânica (SIMULADA — não é evidência)", "", f"_{STUB_BANNER}_", ""] + [
            ln.replace("(medido)", "(simulado)").replace("(estimado)", "(simulado)") for ln in _table(sm)]
    L += ["", "## Limitações", "",
          "- Verificação do router usa o mesmo verificador objetivo do avaliador (tem acesso ao ground truth): escalonamento é mais preciso que um LIGHT real.",
          "- memory_qa exige contexto recuperado, não injetado por este harness: execuções `--real` usam só tarefas autocontidas (extraction).",
          "- Preço de nuvem ausente no registry ⇒ custo `null` (nunca 0); modelos locais custam 0 de token (não inclui energia/GPU).",
          "- retry na mesma tarefa/modelo não é executado (retry_count=0 por construção); só escalonamento.", ""]
    return "\n".join(L)
