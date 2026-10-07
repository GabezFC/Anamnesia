#!/usr/bin/env python
"""Experiment harness (spec anamnesia-orquestracao-de-subagentes §5).

Runs the same task under the 3 presets x N repetitions and prints tokens / cost per role.
Default: STUB launcher (no model, no network; token counts are synthetic and labelled `stub`).
`--real` is required to call real models AND at least one model must be usable now; otherwise it refuses.
The "cheaper" label is never printed here: it needs cost lower AND tests passing equally (spec §5), and this
script does not run tests - `--tests-passed` can be supplied per preset to evaluate the rule.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.orchestration.config import load_config  # noqa: E402
from app.orchestration.launchers import FakeLauncher, InProcessModelLauncher  # noqa: E402
from app.orchestration.orchestrator import Orchestrator  # noqa: E402
from app.routing.registry import load_registry  # noqa: E402

ROLES = ("researcher", "implementer", "reviewer")


def _fmt(v):
    return "-" if v is None else (f"{v:.6f}" if isinstance(v, float) else str(v))


def run_experiment(task: str, reps: int, launcher_factory, registry, project: Path, available=None,
                   presets=("economic", "balanced", "max")) -> list:
    rows = []
    for preset in presets:
        for rep in range(1, reps + 1):
            o = Orchestrator(launcher_factory(), registry=registry, config=load_config(),
                             available_providers=available, sync=True)
            s = o.run(task, preset, project)
            for st in s["steps"]:
                if st["role"] not in ROLES:
                    continue
                rows.append({"preset": preset, "rep": rep, "role": st["role"], "state": s["state"],
                             "model_id": st.get("model_id"), "tokens_in": st.get("input_tokens"),
                             "tokens_out": st.get("output_tokens"), "cost": st.get("cost_usd"),
                             "cost_label": st.get("cost_status", "unavailable"),
                             "latency_ms": st.get("latency_ms")})
    return rows


def render(rows: list, source: str) -> str:
    hdr = f"{'preset':<9}{'rep':>3} {'role':<12}{'model':<18}{'tok_in':>8}{'tok_out':>8}{'cost_usd':>12}  label       ms"
    out = [f"source: {source}", hdr, "-" * len(hdr)]
    for r in rows:
        out.append(f"{r['preset']:<9}{r['rep']:>3} {r['role']:<12}{_fmt(r['model_id']):<18}"
                   f"{_fmt(r['tokens_in']):>8}{_fmt(r['tokens_out']):>8}{_fmt(r['cost']):>12}  "
                   f"{r['cost_label']:<11}{_fmt(r['latency_ms'])}")
    agg = {}
    for r in rows:
        a = agg.setdefault(r["preset"], {"cost": 0.0, "known": 0, "n": 0})
        a["n"] += 1
        if r["cost"] is not None:
            a["cost"] += r["cost"]
            a["known"] += 1
    out.append("")
    for p, a in agg.items():
        total = f"{a['cost']:.6f}" if a["known"] == a["n"] else ("unavailable" if a["known"] == 0
                                                                   else f"{a['cost']:.6f} (partial {a['known']}/{a['n']})")
        out.append(f"total {p:<9} cost_usd: {total}")
    return "\n".join(out)


def cheaper_label(rows: list, tests_passed: dict) -> str:
    """Spec §5: 'economic' is 'mais barata' only if cost fell vs balanced AND the tests passed in equal number."""
    def total(p):
        rs = [r for r in rows if r["preset"] == p]
        if not rs or any(r["cost"] is None for r in rs):
            return None
        return sum(r["cost"] for r in rs)
    e, b = total("economic"), total("balanced")
    if e is None or b is None or "economic" not in tests_passed or "balanced" not in tests_passed:
        return "no label (cost or test results unavailable)"
    if e < b and tests_passed["economic"] == tests_passed["balanced"]:
        return "economic: cheaper"
    return "no label (cost did not fall or tests differ)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task", default="Corrigir um bug pequeno no parser e revisar o diff")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--real", action="store_true", help="call REAL models (needs a usable model)")
    ap.add_argument("--project", help="project dir (default: a temp dir)")
    ap.add_argument("--tests-passed", nargs="*", default=[], metavar="PRESET=N")
    args = ap.parse_args(argv)
    if args.reps < 1:
        ap.error("--reps must be >= 1")
    registry = load_registry()
    if args.real:
        from app.routing.answer import get_availability, usable_registry
        usable = usable_registry(registry, get_availability())
        if not usable.models:
            print("refusing --real: no model is usable (no reachable provider / API key).", file=sys.stderr)
            return 2
        available = {m.provider for m in usable.models}
        factory = lambda: InProcessModelLauncher(usable)  # noqa: E731
        source = "REAL models"
    else:
        available = None
        factory = lambda: FakeLauncher(input_tokens=1000, output_tokens=300)  # noqa: E731
        source = "STUB launcher (synthetic token counts; not a measurement)"
    ctx = tempfile.TemporaryDirectory() if not args.project else None
    project = Path(args.project or ctx.name)
    try:
        rows = run_experiment(args.task, args.reps, factory, registry, project, available)
    finally:
        if ctx:
            ctx.cleanup()
    print(render(rows, source))
    passed = {k: int(v) for k, v in (kv.split("=") for kv in args.tests_passed)}
    print("\nlabel:", cheaper_label(rows, passed) if not source.startswith("STUB")
          else "no label (stub run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
