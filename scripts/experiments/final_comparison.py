"""Final three-pipeline comparison against the REAL JEV API. Writes JSON + a readable table.

Usage:  python scripts/experiments/final_comparison.py [--out reports/final.json]
        [--baseline reports/previous.json [--max-regression-pp 2.0]]

AUD-055 quality gate: with --baseline, the run FAILS (exit 1) when a pipeline's recall drops more than
`--max-regression-pp` percentage points versus the baseline run, or when empty contexts increase.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.gateway.memory_gateway import MemoryGateway  # noqa: E402

PIPELINES = ("baseline", "graphify", "graphify_jev")
MAX_REGRESSION_PP = 2.0   # recall drop (percentage points) tolerated as noise between two runs


def regression_gate(current: dict, baseline: dict, max_regression_pp: float = MAX_REGRESSION_PP) -> list[str]:
    """Violations (empty list = pass) of `current` vs `baseline` (both final_comparison reports).

    A pipeline missing from `current` is a violation too: silently dropping a pipeline hides regressions."""
    out: list[str] = []
    for p, base in (baseline.get("pipelines") or {}).items():
        cur = (current.get("pipelines") or {}).get(p)
        if cur is None:
            out.append(f"{p}: ausente no run atual")
            continue
        drop = float(base["recall_pct"]) - float(cur["recall_pct"])
        if drop > max_regression_pp:
            out.append(f"{p}: recall {base['recall_pct']}% -> {cur['recall_pct']}% (queda {drop:.1f}pp > {max_regression_pp}pp)")
        if cur["empty_contexts"] > base["empty_contexts"]:
            out.append(f"{p}: contextos vazios {base['empty_contexts']} -> {cur['empty_contexts']}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--baseline", default="", help="previous report JSON; exit 1 on regression (AUD-055)")
    ap.add_argument("--max-regression-pp", type=float, default=MAX_REGRESSION_PP)
    a = ap.parse_args()

    gw = MemoryGateway()
    gw.jev = gw.make_jev(gw.jev_cfg, cache=False)
    gw.warm()
    questions = json.loads(Path("benchmark/questions.json").read_text(encoding="utf-8"))
    qs = [q for q in questions if q.get("answerable")]

    report: dict = {"questions": len(qs), "pipelines": {}}
    for p in PIPELINES:
        hits = empty = fb = 0
        ctx, tot, lat, jin = [], [], [], []
        per_q = []
        for q in qs:
            r = gw.search(q["question"], pipeline=p, max_results=10, persist=False)
            m = r.metrics
            got = {s.file for s in r.sources}
            ok = bool(set(q["expected_sources"]) & got)
            hits += ok
            empty += m["context_tokens"] == 0
            fb += bool(m.get("jev_fallback_used"))
            ctx.append(m["context_tokens"])
            tot.append(m["total_tokens_spent"])
            lat.append(m["total_latency_ms"])
            jin.append(m.get("jev_input_tokens") or 0)
            per_q.append({"id": q["id"], "ok": ok, "context_tokens": m["context_tokens"],
                          "total_tokens_spent": m["total_tokens_spent"],
                          "latency_ms": m["total_latency_ms"],
                          "fallback": m.get("jev_fallback_used") or 0})
        report["pipelines"][p] = {
            "recall": f"{hits}/{len(qs)}", "recall_pct": round(hits / len(qs) * 100, 1),
            "empty_contexts": empty, "fallback_used": fb,
            "context_tokens_median": st.median(ctx),
            "total_tokens_median": st.median(tot),
            "judge_input_median": st.median(jin),
            "latency_ms_median": st.median(lat),
            "per_question": per_q,
        }

    print("COMPARATIVO FINAL — JEV real, %d perguntas respondiveis\n" % len(qs))
    hdr = f"{'pipeline':<15}{'recall':<9}{'ctx_med':<10}{'total_med':<11}{'juiz_med':<10}{'lat_med':<10}{'vazios':<7}"
    print(hdr)
    print("-" * len(hdr))
    for p in PIPELINES:
        d = report["pipelines"][p]
        print(f"{p:<15}{d['recall']:<9}{d['context_tokens_median']:<10,.0f}"
              f"{d['total_tokens_median']:<11,.0f}{d['judge_input_median']:<10,.0f}"
              f"{d['latency_ms_median']:<10,.0f}{d['empty_contexts']:<7}")

    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON: {out}")

    if a.baseline:
        bad = regression_gate(report, json.loads(Path(a.baseline).read_text(encoding="utf-8")), a.max_regression_pp)
        print("\nQUALITY GATE:", "FALHOU" if bad else "ok")
        for line in bad:
            print("  -", line)
        if bad:
            sys.exit(1)


if __name__ == "__main__":
    main()
