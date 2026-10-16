"""Onda 4e - routing REAL via OpenRouter, with a hard spending cap (ANA-165/168).

Stages (each is resumable; state lives in data/onda4e_*.json, never any credential):
  python scripts/run_onda4e_openrouter.py integration   # ANA-171/177/178/187: real provider errors vs taxonomy
  python scripts/run_onda4e_openrouter.py bench [--repeats K]   # preflight -> parallel prewarm -> benchmark
  python scripts/run_onda4e_openrouter.py analyze       # ANA-170/189 calibration + ANA-185 LIGHT verifier (offline, $0)

The key is read from the Hermes .env into THIS process only (scripts/_or_env.py); it is never printed/logged/written.
Spending: real spend is measured by GET /api/v1/credits (total_usage) against a baseline stored at the first run.
CAP_USD = 8.00 total; STOP_FRACTION = 0.80: at 80% of the cap new paid calls are refused (kill-switch
ANAMNESIA_PAID_CALLS=0 is also set in-process) and the run aborts, keeping what was measured.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import _or_env  # noqa: E402

DATA = ROOT / "data"
STATE = DATA / "onda4e_state.json"
CACHE = DATA / "onda4e_cache.json"
CELLS = DATA / "onda4e_cells.json"
BENCH_JSON = DATA / "onda4e_bench.json"
INTEG_JSON = DATA / "onda4e_integration.json"
CAP_USD = 8.00
STOP_FRACTION = 0.80
STOP_USD = CAP_USD * STOP_FRACTION
API = "https://openrouter.ai/api/v1"
MODEL_IDS = ["openrouter-gpt4o-mini", "openrouter-gpt41-mini", "openrouter-sonnet"]   # tiers 1, 2, 3
DEFAULT_ID = "openrouter-gpt41-mini"
POLICIES = ["balanced", "economic", "max"]
WORKERS = 6


# ------------------------------------------------------------------ credits (the only source of truth for money)
class Credits:
    def __init__(self):
        import httpx
        self._httpx = httpx
        self._h = {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}

    def usage(self) -> dict:
        r = self._httpx.get(f"{API}/credits", headers=self._h, timeout=20)
        r.raise_for_status()
        d = r.json()["data"]
        return {"total_credits": float(d["total_credits"]), "total_usage": float(d["total_usage"])}


def load_state(c: Credits) -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    u = c.usage()
    st = {"baseline_usage": u["total_usage"], "credits_at_start": u["total_credits"], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    DATA.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return st


def spent_now(c: Credits, st: dict) -> float:
    return round(c.usage()["total_usage"] - st["baseline_usage"], 6)


class SpendGuard:
    """Wraps a runner. Thread-safe. Refuses the NEXT call once the REAL spend (credits API, polled every
    `poll_every` calls; local price-based tally in between) reached STOP_USD, and flips the kill-switch."""

    def __init__(self, inner, credits: Credits, st: dict, poll_every: int = 15):
        self._inner, self._c, self._st = inner, credits, st
        self.poll_every, self.calls, self.local_est, self.api_spent, self.stopped = poll_every, 0, 0.0, 0.0, False
        self._lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _check(self):
        from app.benchmark.preflight import BudgetExceeded
        if self.stopped:
            raise BudgetExceeded(f"stop at US$ {self.api_spent:.4f} >= {STOP_USD:.2f}")
        if self.calls % self.poll_every == 0:
            self.api_spent = spent_now(self._c, self._st)
        if self.api_spent >= STOP_USD or self.local_est >= STOP_USD:
            self.stopped = True
            os.environ["ANAMNESIA_PAID_CALLS"] = "0"            # ANA-168 kill-switch, in-process
            raise BudgetExceeded(f"stop at US$ {max(self.api_spent, self.local_est):.4f} >= {STOP_USD:.2f}")

    def __call__(self, task, entry):
        from app.benchmark import routing_bench as rb
        with self._lock:
            self._check()
            self.calls += 1
        out = self._inner(task, entry)
        c, _ = rb.call_cost(entry, out)
        if c:
            with self._lock:
                self.local_est += c
        return out


# ------------------------------------------------------------------ shared setup
def make_env(with_context: bool = True):
    from app.benchmark import routing_bench as rb
    from app.routing.registry import Registry, load_registry
    from app.routing.tasks import load_tasks
    reg = load_registry()
    models = [reg.get(i) for i in MODEL_IDS]
    for m in models:
        assert m.verified and m.price is not None and m.context_window, f"{m.id}: registry not verified/priced"
    tasks = load_tasks() + load_tasks(ROOT / "benchmark" / "routing_tasks_code.json")
    tasks = sorted(tasks, key=lambda t: t.id)
    assert len({t.id for t in tasks}) == len(tasks)
    # ANA-001/002 gate: expected fact must not occur in the query
    leaks = [t.id for t in tasks if any(rb.normalize(f) in rb.normalize(t.query)
                                        for f in t.ground_truth.get("expected_facts", []) if f)]
    assert not leaks, f"leaked ground truth in query: {leaks[:5]}"
    memo = None
    if with_context:
        from app.gateway.memory_gateway import MemoryGateway
        gw = MemoryGateway()
        gw.warm()
        memo = rb.GatewayContext(gw)
        for t in tasks:
            if t.kind == "memory_qa":
                memo(t)                                          # serial: sqlite-safe, memoised
    registry = Registry(models=models, file_hash="bench-" + __import__("hashlib").sha256(
        ",".join(sorted(m.id for m in models)).encode()).hexdigest()[:12], version="bench")
    return rb, models, tasks, memo, registry


def make_runner_cls(rb):
    from app.routing.answer import make_adapter  # noqa: F401

    class Runner(rb.RealRunner):
        """RealRunner + transient-error retry (rate_limit/timeout/provider_down) + error_kind log (ANA-171/177/178)."""
        error_log: list = []
        _lock = threading.Lock()

        def __call__(self, task, entry):
            from app.services.token_estimate import detect_lang, estimate_tokens
            prompt = self.prompt_for(task)
            r = None
            for attempt in range(3):
                r = self._adapter(entry).generate(prompt, temperature=0.0, max_tokens=self.max_tokens)
                if not r.error:
                    break
                with Runner._lock:
                    Runner.error_log.append({"task": task.id, "model": entry.id, "attempt": attempt,
                                             "kind": r.error_kind, "status": r.status_code})
                if r.error_kind not in ("rate_limit", "timeout", "provider_down"):
                    break
                time.sleep(min(20.0, (r.retry_after or 2.0 * (attempt + 1))))
            retrieved = None
            so = getattr(self.context_fn, "sources_of", None)
            if so is not None and task.kind == "memory_qa":
                retrieved = so(task)
            return rb.RunOutcome(r.answer, r.input_tokens, r.output_tokens, r.latency_ms, r.error, simulated=False,
                                 retrieved_ids=retrieved, estimated_input_tokens=estimate_tokens(prompt),
                                 prompt_lang=detect_lang(prompt))
    return Runner


# ------------------------------------------------------------------ stage: integration (ANA-171/177/178/187)
def stage_integration():
    from app.adapters.models.errors import ERROR_KINDS
    from app.adapters.models.providers import OpenRouterAdapter
    from app.routing import circuit_breaker as cb
    from app.routing import resilience as rs
    from app.routing import retry as rt
    import httpx
    c = Credits()
    st = load_state(c)
    before = spent_now(c, st)
    out: dict = {"cases": [], "spent_before": before}

    def case(name, expect, gen):
        t0 = time.perf_counter()
        r = gen()
        row = {"case": name, "expected_kind": expect, "error_kind": r.error_kind, "status_code": r.status_code,
               "retry_after": r.retry_after, "ok": r.error_kind == expect, "error_head": (r.error or "")[:90],
               "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "tokens": [r.input_tokens, r.output_tokens]}
        out["cases"].append(row)
        print(row["case"], "->", row["error_kind"], row["status_code"], "ok" if row["ok"] else "MISMATCH")
        return r

    bad = OpenRouterAdapter("openai/this-model-does-not-exist-onda4e")
    case("nonexistent_model_404", "model_not_found", lambda: bad.generate("ping", max_tokens=1))
    big_a = OpenRouterAdapter("openai/gpt-4o-mini")
    huge = "palavra " * 130000                                  # ~160k+ tokens > 128k window; rejected before inference
    case("context_overflow_gpt4o_mini", "context_overflow", lambda: big_a.generate(huge, max_tokens=1))
    to = OpenRouterAdapter("openai/gpt-4o-mini")
    to.timeout_s = httpx.Timeout(connect=15.0, read=0.05, write=15.0, pool=15.0)
    case("read_timeout_50ms", "timeout", lambda: to.generate("Diga ok.", max_tokens=1))
    # control: a valid tiny call proves the happy path is classified error_kind=None and measures real usage
    ok = OpenRouterAdapter("openai/gpt-4o-mini")
    case("control_valid_call", None, lambda: ok.generate("Responda apenas: ok", max_tokens=3))

    # decision table (ANA-177) fed with the REAL kinds just observed
    out["decisions"] = {}
    for row in out["cases"]:
        k = row["error_kind"]
        if k:
            a = rs.decide(k, attempt=0, retry_after=row["retry_after"], max_retries=1, has_larger_window=False)
            out["decisions"][k] = {"action": a.name, "delay_s": a.delay_s, "reason": a.reason}

    # retry (ANA-178) + breaker (ANA-187) on a REAL persistent failure (nonexistent model)
    os.environ["ANAMNESIA_RETRY"] = "1"
    os.environ["ANAMNESIA_CIRCUIT_BREAKER"] = "1"
    cb.reset_breaker()
    from app.routing.registry import ModelEntry
    ghost = ModelEntry("ghost", "openrouter", "openai/this-model-does-not-exist-onda4e", 1)
    infos = []
    for _ in range(4):
        info: dict = {}
        r = rs.guarded_generate(ghost, lambda e, a: OpenRouterAdapter(e.model), None, "ping", info, max_tokens=1)
        infos.append({"kind": r.error_kind, "retries": info.get("retries"), "gave_up": info.get("gave_up"),
                      "circuit_open": info.get("circuit_open", False)})
    out["retry_breaker_not_found"] = {"attempts": infos, "retryable_kinds": sorted(rt.RETRYABLE_KINDS),
                                      "tripping_kinds": sorted(cb.TRIPPING_KINDS),
                                      "note": "model_not_found: not retryable (1 attempt, gave_up=not_retryable) but it DOES count toward opening the breaker (3 failures -> 4th call blocked)"}
    # breaker on a REAL endpoint failure: timeout (read 50ms) x3 -> open -> 4th call not sent
    cb.reset_breaker()
    tmo = ModelEntry("slow", "openrouter", "openai/gpt-4o-mini", 1)

    def tiny_timeout_adapter(e, a):
        ad = OpenRouterAdapter(e.model)
        ad.timeout_s = httpx.Timeout(connect=15.0, read=0.05, write=15.0, pool=15.0)
        return ad
    os.environ["ANAMNESIA_CIRCUIT_BREAKER"] = "0"                 # ANA-178: retry alone on a REAL timeout
    os.environ["ANAMNESIA_RETRY"] = "1"
    info = {}
    r = rs.guarded_generate(tmo, tiny_timeout_adapter, None, "Diga ok.", info, max_tokens=1)
    out["retry_on_real_timeout"] = {"kind": r.error_kind, "retries": info.get("retries"), "waited_s": info.get("waited_s"),
                                    "gave_up": info.get("gave_up"), "log": info.get("retry_log")}
    os.environ["ANAMNESIA_CIRCUIT_BREAKER"] = "1"
    cb.reset_breaker()
    os.environ["ANAMNESIA_RETRY"] = "0"                           # isolate the breaker from retries
    seq = []
    for _ in range(5):
        info = {}
        r = rs.guarded_generate(tmo, tiny_timeout_adapter, None, "Diga ok.", info, max_tokens=1)
        seq.append({"kind": r.error_kind, "circuit_open": info.get("circuit_open", False)})
    out["breaker_on_real_timeouts"] = {"sequence": seq, "state": cb.get_breaker().state(cb.key_for("openrouter", tmo.model)),
                                       "tripping_kinds": sorted(cb.TRIPPING_KINDS)}
    # kill-switch ANA-168 against the real adapter factory: must raise BEFORE any network
    from app.routing.answer import make_adapter
    os.environ["ANAMNESIA_PAID_CALLS"] = "0"
    try:
        make_adapter(ok_entry := ModelEntry("x", "openrouter", "openai/gpt-4o-mini", 1))
        ks = "NOT BLOCKED"
    except Exception as e:  # noqa: BLE001
        ks = type(e).__name__
    del os.environ["ANAMNESIA_PAID_CALLS"]
    out["kill_switch"] = {"make_adapter_openrouter_with_flag_off": ks}
    out["taxonomy"] = list(ERROR_KINDS)
    out["observed_kinds"] = sorted({r["error_kind"] for r in out["cases"] if r["error_kind"]})
    out["not_tested_on_purpose"] = ["auth (no invalid keys)", "rate_limit (429 not provoked)", "bad_output", "provider_down 5xx"]
    out["spent_after"] = spent_now(c, st)
    out["spent_stage_usd"] = round(out["spent_after"] - before, 6)
    out["all_ok"] = all(r["ok"] for r in out["cases"]) and ks == "PaidCallsDisabled"
    INTEG_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("all_ok", "spent_stage_usd", "kill_switch", "observed_kinds")}))
    return 0 if out["all_ok"] else 1


# ------------------------------------------------------------------ stage: bench
def prewarm(cache, runner, tasks, models, rep: int) -> dict:
    jobs = [(t, m) for t in tasks for m in models if cache.key_for(t, m, runner, rep) not in cache.cells]
    stats = {"rep": rep, "jobs": len(jobs), "ok": 0, "error": 0, "aborted": False}
    lock = threading.Lock()

    def one(t, m):
        return t, m, runner(t, m)

    with ThreadPoolExecutor(WORKERS) as ex:
        futs = [ex.submit(one, t, m) for t, m in jobs]
        n = 0
        for f in as_completed(futs):
            try:
                t, m, out = f.result()
            except Exception as e:  # noqa: BLE001  (BudgetExceeded)
                stats["aborted"] = True
                stats["abort_reason"] = f"{type(e).__name__}: {str(e)[:100]}"
                continue
            if out.error:
                stats["error"] += 1
                continue
            k = cache.key_for(t, m, runner, rep)
            with lock:
                cache.cells[k] = out
                cache.manifest[k] = {"task_id": t.id, "model_id": m.id, "prompt_version": rb_version(),
                                     "params": getattr(runner, "cache_params", None),
                                     "registry_version": cache.registry_version, "rep": rep, "created": time.time()}
                cache.executions += 1
                stats["ok"] += 1
                n += 1
                if n % 100 == 0:
                    cache.save()
    cache.save()
    return stats


def rb_version() -> str:
    from app.benchmark import routing_bench as rb
    return rb.PROMPT_VERSION


def power_gate(n_tasks: int, allow_underpowered: bool = False, p1: float = 0.5, delta: float = 0.10):
    """AUD-054: refuse to spend money on a benchmark that cannot detect `delta` (Onda4e N=197 had power
    0.514). Returns (power_report, required_n); power_report is None when the run must be refused."""
    from app.benchmark.statistics import power_report, required_n_two_proportions
    pw, need = power_report(n_tasks, p1, delta), required_n_two_proportions(p1, delta)
    print(f"N={n_tasks} tarefas; poder={pw['achieved_power']} para {delta * 100:.0f}pp; necessário ~{need}/braço")
    if pw["sufficient"] or allow_underpowered:
        return pw, need
    print(f"REFUSED underpowered: N={n_tasks} < {need} (poder {pw['achieved_power']} < 0.8). "
          f"Aumente o corpus ou use --allow-underpowered (resultado só exploratório).")
    return None, need


def stage_bench(repeats: int, rep1_budget: float, allow_underpowered: bool = False):
    from app.benchmark import routing_bench as rb
    from app.benchmark.preflight import BudgetExceeded, preflight
    c = Credits()
    st = load_state(c)
    bal = c.usage()
    print(f"credits total={bal['total_credits']} usage={bal['total_usage']} spent_since_baseline={spent_now(c, st)}")
    assert bal["total_credits"] - bal["total_usage"] > CAP_USD - spent_now(c, st), "saldo insuficiente para o teto"
    rb_, models, tasks, memo, registry = make_env()
    pw, need = power_gate(len(tasks), allow_underpowered)
    if pw is None:
        return 2
    Runner = make_runner_cls(rb)
    raw = Runner(timeout_s=90.0, context_fn=memo, max_tokens=400)
    cache = rb.ResultCache(CACHE, registry_version=registry.version_hash())
    cache.registry_version = registry.version_hash()
    strategies = [rb.STATIC_CHEAP, rb.STATIC_DEFAULT, rb.STATIC_STRONG, rb.DYNAMIC_ROUTER, rb.ORACLE] + list(rb.CONTROL_STRATEGIES)
    pf = preflight(tasks, models, strategies, repeats=repeats, max_usd=STOP_USD, default_id=DEFAULT_ID, max_tokens=400,
                   prompt_fn=raw.prompt_for)
    print("preflight:", json.dumps({k: pf.as_dict()[k] for k in ("ok", "reason", "estimate_usd", "estimate_origin", "n_calls")}))
    if not pf.ok:
        print("REFUSED", pf.reason)
        return 2
    guard = SpendGuard(raw, c, st)
    pre = []
    try:
        for rep in range(repeats):
            if rep == 1:
                sp = spent_now(c, st)
                if sp > rep1_budget:
                    print(f"rep1 skipped: spent {sp} > {rep1_budget}")
                    repeats = 1
                    break
            s = prewarm(cache, guard, tasks, models, rep)
            print("prewarm", s, "spent", spent_now(c, st))
            pre.append(s)
            if s["aborted"]:
                break
        result = rb.run_benchmark(tasks, models, guard, strategies, POLICIES, DEFAULT_ID, cache, repeats=repeats)
        aborted = None
    except BudgetExceeded as e:
        aborted = str(e)
        print("ABORTED", aborted)
        cache.save()
        result = None
    spent = spent_now(c, st)
    meta = {"spent_usd_api": spent, "local_price_estimate_usd": round(guard.local_est, 6), "calls_through_guard": guard.calls,
            "preflight": pf.as_dict(), "prewarm": pre, "aborted": aborted, "repeats": repeats, "n_tasks": len(tasks),
            "power": pw, "required_n_per_arm_10pp": need, "error_log": Runner.error_log[:50], "n_errors": len(Runner.error_log),
            "cap_usd": CAP_USD, "stop_usd": STOP_USD, "baseline_usage": st["baseline_usage"]}
    if result is not None:
        meta["bench_meta"] = result.meta
        recs = [{k: v for k, v in r.items() if not k.startswith("_")} for r in result.records]
        BENCH_JSON.write_text(json.dumps({"meta": meta, "records": recs}, ensure_ascii=False, default=str), encoding="utf-8")
        # per task x model x rep cells (all from cache) for the offline analysis
        dump_cells(rb, cache, raw, tasks, models, memo, repeats)
        from app.database.db import Database
        dbp = DATA / "onda4e_bench.db"
        if dbp.exists():
            dbp.unlink()
        ids = rb.persist(Database(str(dbp)), result)
        meta["persisted_runs"] = len(ids)
        (DATA / "onda4e_report.md").write_text(rb.render_report(result, time.strftime("%Y-%m-%d"), True, [
            f"gasto real (API /credits) US$ {spent}", f"N={len(tasks)} (poder {pw['achieved_power']} para 10pp; necessário ~{need}/braço)"]),
            encoding="utf-8")
        BENCH_JSON.write_text(json.dumps({"meta": meta, "records": recs}, ensure_ascii=False, default=str), encoding="utf-8")
    print("spent_api", spent, "local_est", round(guard.local_est, 6), "calls", guard.calls, "errors", len(Runner.error_log))
    return 0 if not aborted else 3


def dump_cells(rb, cache, runner, tasks, models, memo, repeats):
    rows = []
    for t in tasks:
        for m in models:
            for rep in range(repeats):
                k = cache.key_for(t, m, runner, rep)
                o = cache.cells.get(k)
                if o is None:
                    continue
                res = rb.verify_task(t, o.answer, o.retrieved_ids)
                c, origin = rb.call_cost(m, o)
                rows.append({"task": t.id, "model": m.id, "tier": m.tier, "rep": rep, "solved": bool(res.passed),
                             "failure_code": res.failure_code, "cost": c, "cost_origin": origin, "in": o.input_tokens,
                             "out": o.output_tokens, "latency_ms": o.latency_ms, "answer": o.answer,
                             "retrieved": o.retrieved_ids, "error": o.error})
    ctx = {t.id: memo(t) for t in tasks if t.kind == "memory_qa"} if memo else {}
    CELLS.write_text(json.dumps({"cells": rows, "context": ctx}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["integration", "bench", "status"])
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--rep1-budget", type=float, default=3.0, help="skip rep>=1 if spend already exceeds this (US$)")
    ap.add_argument("--allow-underpowered", action="store_true",
                    help="run even if N < n required for 80%% power at 10pp (result is exploratory only)")
    a = ap.parse_args()
    if not _or_env.load():
        print("BLOCKED: OPENROUTER_API_KEY not found", file=sys.stderr)
        sys.exit(2)
    if a.stage == "status":
        cc = Credits()
        s_ = load_state(cc)
        print(json.dumps({**cc.usage(), "spent_since_baseline": spent_now(cc, s_), "cap": CAP_USD, "stop": STOP_USD}))
        sys.exit(0)
    sys.exit(stage_integration() if a.stage == "integration" else stage_bench(a.repeats, a.rep1_budget, a.allow_underpowered))
