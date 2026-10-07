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
    a = ap.parse_args(argv)

    strategies = (a.strategies.split(",") if a.strategies
                  else ([rb.STATIC_CHEAP, rb.STATIC_STRONG] if a.real else list(rb.ALL_STRATEGIES)))
    strategies = [s.strip() for s in strategies if s.strip()]
    bad = [s for s in strategies if s not in rb.ALL_STRATEGIES]
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
        runner = rb.RealRunner(timeout_s=a.timeout)
        full = len(tasks)
        tasks = [t for t in tasks if rb.is_self_contained(t)]
        notes.append(f"--real: {len(tasks)} de {full} tarefas autocontidas (extraction); memory_qa excluída (sem contexto injetado)")
    else:
        models = registry.models
        runner = rb.StubRunner()
        print(f"*** {rb.STUB_BANNER} ***")
    sample = rb.sample_tasks(tasks, a.sample, a.seed)
    cache = rb.ResultCache(a.cache)
    result = rb.run_benchmark(sample, models, runner, strategies, a.policies.split(","), a.default_model, cache)

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
