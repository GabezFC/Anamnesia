"""CLI for the routing benchmark (R6).

  python scripts/run_routing_benchmark.py --sample 20                    # SIMULATED stub runner, all strategies
  python scripts/run_routing_benchmark.py --real --sample 10 --strategies STATIC_CHEAP,STATIC_STRONG

--real only runs when at least one registry model is usable NOW (local Ollama reachable with the model
installed, or a provider key present); otherwise it refuses (exit 2). The stub runner always prints the banner
'SIMULATED (stub runner): numbers are NOT evidence'. Results go to an explicit --db only (never benchmark.db by default).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.benchmark import routing_bench as rb  # noqa: E402
from app.routing.registry import Registry, load_registry  # noqa: E402
from app.routing.tasks import load_tasks  # noqa: E402


def usable_models(registry: Registry) -> Registry:
    from app.routing.answer import get_availability, usable_registry
    return usable_registry(registry, get_availability())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", action="store_true", help="call real models (only if one is usable)")
    ap.add_argument("--sample", type=int, default=20, help="stratified sample size (default 20)")
    ap.add_argument("--strategies", default=None, help="comma list of " + ",".join(rb.ALL_STRATEGIES))
    ap.add_argument("--policies", default="balanced", help="router presets, comma list (economic,balanced,max)")
    ap.add_argument("--default-model", default=None, help="registry id used by STATIC_DEFAULT")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=float, default=120.0, help="per-call cap in seconds (real runner)")
    ap.add_argument("--cache", default=None, help="JSON file persisting the task x model cache")
    ap.add_argument("--db", default=None, help="explicit SQLite path to persist runs (never defaults to benchmark.db)")
    ap.add_argument("--out", default=None, help="report path (default docs/ROUTING_BENCHMARK_<date>[_SIMULATED].md)")
    ap.add_argument("--tasks", default=None, help="tasks json (default benchmark/routing_tasks.json)")
    ap.add_argument("--with-memory", action="store_true",
                    help="--real: include memory_qa, injecting context retrieved by the gateway (ANA-019)")
    ap.add_argument("--min-n", type=int, default=None,
                    help="--real: minimum sample size; default = n needed to detect a 10 p.p. difference at 80%% "
                         "power (ANA-014). Below it the run is refused unless --allow-underpowered")
    ap.add_argument("--allow-underpowered", action="store_true", help="--real: run below --min-n (report says so)")
    ap.add_argument("--repeats", type=int, default=1,
                    help="ANA-110: run each (task, model) K times (key task,model,rep) and report the std between reps")
    ap.add_argument("--strata", choices=("cell", "difficulty"), default="cell",
                    help="ANA-112: sample stratification (default kind x difficulty x answerable)")
    ap.add_argument("--max-usd", type=float, default=None,
                    help="ANA-165: --real spending ceiling in US$. Estimate > ceiling, or a paid model with unknown price "
                         "and no ceiling, is REFUSED (exit 2, no call); the run aborts (exit 3) if the real spend exceeds it")
    ap.add_argument("--local-gpu-usd-per-hour", type=float, default=None,
                    help="ANA-191: optional ASSUMPTION (estimated) of US$/GPU-hour for local models; adds a cost/solved "
                         "'with local cost' line to the report. Off by default")
    a = ap.parse_args(argv)

    strategies = (a.strategies.split(",") if a.strategies
                  else ([rb.STATIC_CHEAP, rb.STATIC_STRONG] if a.real else list(rb.ALL_STRATEGIES)))
    strategies = [s.strip() for s in strategies if s.strip()]
    if not a.strategies:   # ANA-016: negative controls always ride along (free: no model call)
        strategies += [c for c in rb.CONTROL_STRATEGIES if c not in strategies]
    bad = [s for s in strategies if s not in rb.ALL_STRATEGIES + rb.CONTROL_STRATEGIES]
    if bad:
        print(f"unknown strategies: {bad}", file=sys.stderr)
        return 2

    registry = load_registry()
    tasks = load_tasks(a.tasks) if a.tasks else load_tasks()
    notes: list[str] = []
    if a.real:
        usable = usable_models(registry)
        if not usable.models:
            print("REFUSED: --real but no usable model (no reachable Ollama model / provider key). "
                  "No call was made. Run without --real for the SIMULATED stub.", file=sys.stderr)
            return 2
        models = usable.models
        full = len(tasks)
        if a.with_memory:
            from app.gateway.memory_gateway import MemoryGateway
            gw = MemoryGateway()
            gw.warm()
            runner = rb.RealRunner(timeout_s=a.timeout, context_fn=rb.GatewayContext(gw))
            notes.append(f"--real --with-memory: memory_qa com contexto recuperado pelo gateway ({full} tarefas)")
        else:
            runner = rb.RealRunner(timeout_s=a.timeout)
            tasks = [t for t in tasks if rb.is_self_contained(t)]
            notes.append(f"--real: {len(tasks)} de {full} tarefas autocontidas (extraction); memory_qa excluída (use --with-memory)")
    else:
        models = registry.models
        runner = rb.StubRunner()
        print(f"*** {rb.STUB_BANNER} ***")
    sample = rb.sample_tasks(tasks, a.sample, a.seed, strata=a.strata)
    coverage = rb.sample_coverage(tasks, sample)
    notes.append(f"amostra: {len(sample)} tarefas; células kind×dificuldade×answerable cobertas "
                 f"{coverage['cells_covered']}/{coverage['cells_total']}; abstenções {coverage['unanswerable_in_sample']}")
    if a.real:   # ANA-014: refuse an underpowered paid run, and always print the power
        from app.benchmark.statistics import power_report, required_n_two_proportions
        need = a.min_n if a.min_n is not None else required_n_two_proportions(0.5, 0.10)
        pw = power_report(len(sample))
        msg = (f"N={pw['n']} por braço; poder estimado={pw['achieved_power']} para detectar {pw['min_detectable_delta']:.0%} "
               f"(taxa-base {pw['baseline_rate']:.0%}); necessário ~{pw['required_n_per_arm']} por braço")
        print(msg)
        notes.append("poder: " + msg)
        if len(sample) < need and not a.allow_underpowered:
            print(f"REFUSED: amostra {len(sample)} < minimo {need} (ANA-014). Nenhuma chamada foi feita. "
                  "Aumente --sample, reduza --min-n ou use --allow-underpowered.", file=sys.stderr)
            return 2
        if len(sample) < need:
            notes.append(f"**SUBDIMENSIONADO**: N={len(sample)} < {need}; diferenças pequenas não são detectáveis")
    guard = pf = None
    if a.real:   # ANA-165: bound the spend BEFORE the first paid call
        from app.benchmark.preflight import BudgetedRunner, preflight
        pf = preflight(sample, models, strategies, repeats=a.repeats, max_usd=a.max_usd, default_id=a.default_model,
                       max_tokens=getattr(runner, "max_tokens", 400))
        est = pf.estimate_usd
        print(f"preflight: {pf.n_calls} chamadas, estimativa US$ {est if est is not None else 'indisponível'}"
              f"{'' if pf.complete else ' (limite inferior: preço desconhecido)'}, teto {a.max_usd}")
        notes.append(f"preflight: estimativa US$ {est} ({'completa' if pf.complete else 'limite inferior'}), teto {a.max_usd}")
        if not pf.ok:
            print(f"REFUSED: {pf.reason}. Nenhuma chamada foi feita.", file=sys.stderr)
            return 2
        guard = BudgetedRunner(runner, a.max_usd)
        runner = guard
    cache = rb.ResultCache(a.cache)
    from app.benchmark.preflight import BudgetExceeded
    try:
        result = rb.run_benchmark(sample, models, runner, strategies, a.policies.split(","), a.default_model, cache,
                                  repeats=a.repeats)
    except BudgetExceeded as e:
        rep_ = guard.report(pf.estimate_usd, pf.complete) if guard and pf else {}
        print(f"ABORTED: {e}. relatório parcial: {rep_}", file=sys.stderr)
        return 3
    if guard and pf:
        rep_ = guard.report(pf.estimate_usd, pf.complete)
        result.meta["preflight"] = {**pf.as_dict(), "actual": rep_}
        print(f"gasto real US$ {rep_['spent_usd']} ({rep_['spent_origin']}); razão real/estimado = {rep_['ratio_real_over_estimate']}")
        notes.append(f"gasto real US$ {rep_['spent_usd']}; razão real/estimado {rep_['ratio_real_over_estimate']}")
        if rep_["aborted"]:
            print("ABORTED: o teto foi ultrapassado na última chamada; relatório gravado com o que foi medido.", file=sys.stderr)
    if a.local_gpu_usd_per_hour is not None:   # ANA-191
        from app.routing import metrics as M
        recs = [r for r in result.records if r.get("strategy") == rb.STATIC_DEFAULT or r.get("strategy") == rb.DYNAMIC_ROUTER]
        for st in sorted({r["strategy"] for r in recs}):
            lc = M.local_cost_assumption([r for r in recs if r["strategy"] == st], a.local_gpu_usd_per_hour)
            notes.append(f"ANA-191 {st}: custo/resolvida sem GPU local = {lc['cost_per_solved_without']['value']}; "
                         f"com GPU local (ESTIMADO a US$ {a.local_gpu_usd_per_hour}/h) = {lc['cost_per_solved_with']['value']}")
    result.meta["sample_coverage"] = coverage

    if a.db:
        from app.database.db import Database
        db = Database(a.db)
        ids = rb.persist(db, result)
        print(f"persisted {len(ids)} runs into {a.db}")
    date = time.strftime("%Y-%m-%d")
    out = Path(a.out) if a.out else ROOT / "docs" / f"ROUTING_BENCHMARK_{date}{'' if a.real else '_SIMULATED'}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rb.render_report(result, date, a.real, notes), encoding="utf-8")
    if not a.real:
        print(f"*** {rb.STUB_BANNER} ***")
    print(f"tasks={result.meta['n_tasks']} executions={result.meta['executions']} cache_hits={result.meta['cache_hits']}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
