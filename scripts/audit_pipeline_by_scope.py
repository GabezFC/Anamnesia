"""Pipeline audit segmented by "search size" — item 1.1 of the 2026-09-28 proposal.

Reads benchmark.db read-only (same queries/back-fill logic as scripts/audit_pipeline.py) and
splits the recorded runs into small/medium/large buckets using the REAL quantile distribution
of `candidate_tokens_before_filter` (raw candidates before any filter/JEV step), never an
arbitrary cut. Also splits by corpus (vault_path found inside each run's config_json) when the
DB actually contains more than one corpus.

Per (corpus, scenario, pipeline) cell: n, recall (only when ground truth exists), median
total_tokens_spent, median token_amplification, median latency, jev_fallback/empty-context rate.
Never reports context_reduction alone (decisao-metrica-total-tokens-spent).

Usage:
    python scripts/audit_pipeline_by_scope.py [--db path] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics as st
from collections import defaultdict
from pathlib import Path

PIPELINES = ["baseline", "graphify", "graphify_jev", "graphify_jev_opt"]
MIN_CELL_N = 10  # below this, a cell's numbers are printed but flagged as not conclusive

SIZE_KEY = "candidate_tokens_before_filter"
SIZE_FALLBACK_KEY = "documents_found"


def _corpus_of(config_json: str | None) -> str:
    if not config_json:
        return "unknown"
    m = re.search(r'"vault_path":\s*"([^"]+)"', config_json)
    if not m:
        return "unknown"
    vp = m.group(1)
    if "synthetic" in vp:
        return "synthetic"
    if "Cérebro" in vp or "Cerebro" in vp or "\\u00e9rebro" in vp:
        return "real"
    return vp


def load(db: str) -> list[dict]:
    """One row per run, decorated the same way scripts/audit_pipeline.py does, plus scope fields."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows: list[dict] = []
    q = (
        "select pipeline, mode, config_json, metrics_json, context, sources_json from runs "
        "where mode != 'warmup' and metrics_json is not null and (error is null or error='')"
    )
    for r in con.execute(q):
        m = json.loads(r["metrics_json"])
        # same honest back-fill as audit_pipeline.py, so totals line up across scripts
        judge = (m.get("jev_input_tokens") or 0) + (m.get("jev_output_tokens") or 0)
        m.setdefault("judge_tokens", judge)
        ctx = m.get("context_tokens") or 0
        m.setdefault("total_tokens_spent", judge + ctx)
        if m.get("token_amplification") is None and ctx:
            m["token_amplification"] = round(m["total_tokens_spent"] / ctx, 2)
        exp = m.get("expected_sources_found")
        if isinstance(exp, dict) and "recall" in exp:
            m["_recall"] = exp["recall"]
        m["_pipeline"] = r["pipeline"]
        m["_mode"] = r["mode"]
        m["_corpus"] = _corpus_of(r["config_json"])
        m["_empty_context"] = (m.get("context_tokens") or 0) == 0
        size = m.get(SIZE_KEY)
        if size is None:
            size = m.get(SIZE_FALLBACK_KEY)
        m["_size"] = size
        rows.append(m)
    con.close()
    return rows


def quantile_cuts(sizes: list[float]) -> tuple[float, float]:
    """Tertile cuts (p33, p66) of the real distribution -> small / medium / large."""
    s = sorted(sizes)
    q = st.quantiles(s, n=3, method="inclusive")
    return q[0], q[1]


def scenario_of(size: float | None, cuts: tuple[float, float]) -> str:
    if size is None:
        return "unknown"
    lo, hi = cuts
    if size <= lo:
        return "small"
    if size <= hi:
        return "medium"
    return "large"


def describe_distribution(sizes: list[float]) -> dict:
    s = sorted(sizes)
    n = len(s)
    if n == 0:
        return {}
    def pct(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return s[idx]
    return {
        "n": n, "min": s[0], "p10": pct(0.10), "p25": pct(0.25), "p33": pct(1 / 3),
        "median": pct(0.50), "p66": pct(2 / 3), "p75": pct(0.75), "p90": pct(0.90), "max": s[-1],
    }


def med(rows: list[dict], key: str):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(st.median(vals), 1) if vals else None


def rate(rows: list[dict], pred) -> str:
    if not rows:
        return "—"
    n = sum(1 for r in rows if pred(r))
    return f"{n}/{len(rows)} ({n / len(rows) * 100:.0f}%)"


def cell_stats(rows: list[dict]) -> dict:
    recall_rows = [r for r in rows if "_recall" in r]
    return {
        "n": len(rows),
        "recall_mean": round(sum(r["_recall"] for r in recall_rows) / len(recall_rows), 3) if recall_rows else None,
        "recall_n": len(recall_rows),
        "total_tokens_spent_median": med(rows, "total_tokens_spent"),
        "token_amplification_median": med(rows, "token_amplification"),
        "latency_ms_median": med(rows, "total_latency_ms"),
        "jev_fallback_rate": rate(rows, lambda r: bool(r.get("jev_fallback_used"))),
        "empty_context_rate": rate(rows, lambda r: r["_empty_context"]),
    }


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}" if v != int(v) else f"{int(v):,}"
    return str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "benchmark.db"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = load(a.db)
    sized = [r for r in rows if isinstance(r.get("_size"), (int, float))]

    print("=" * 100)
    print("MEMORY GATEWAY — PIPELINE AUDIT BY SCOPE (search size, real quantile cuts)")
    print("=" * 100)
    print(f"total runs loaded (mode != warmup, no error): {len(rows)}")
    print(f"runs with a usable size metric ({SIZE_KEY} or {SIZE_FALLBACK_KEY}): {len(sized)}")
    print()

    by_pipeline_n = defaultdict(int)
    by_corpus_n = defaultdict(int)
    for r in rows:
        by_pipeline_n[r["_pipeline"]] += 1
        by_corpus_n[r["_corpus"]] += 1
    print("n by pipeline (desbalanceamento real, sem correção):")
    for p in PIPELINES:
        print(f"  {p.ljust(18)} n={by_pipeline_n.get(p, 0)}")
    other = {k: v for k, v in by_pipeline_n.items() if k not in PIPELINES}
    if other:
        print(f"  (other pipeline values found: {other})")
    print()
    print("n by corpus (vault_path found in config_json):")
    for c, n in sorted(by_corpus_n.items()):
        print(f"  {c.ljust(18)} n={n}")
    print()

    dist = describe_distribution([r["_size"] for r in sized])
    print(f"DISTRIBUTION of {SIZE_KEY} (fallback {SIZE_FALLBACK_KEY}), all pipelines/corpora pooled:")
    print(f"  n={dist['n']}  min={fmt(dist['min'])}  p10={fmt(dist['p10'])}  p25={fmt(dist['p25'])}  "
          f"p33={fmt(dist['p33'])}  median={fmt(dist['median'])}  p66={fmt(dist['p66'])}  "
          f"p75={fmt(dist['p75'])}  p90={fmt(dist['p90'])}  max={fmt(dist['max'])}")
    pooled_cuts = quantile_cuts([r["_size"] for r in sized])
    print(f"  pooled tertile cuts: small <= {fmt(pooled_cuts[0])}  |  medium <= {fmt(pooled_cuts[1])}  |  large above")
    print()
    print("  WARNING: the corpora do not share a scale (see per-corpus distribution below). Pooling")
    print("  them produces a bimodal mix where one corpus can dominate a whole bucket by itself.")
    print("  Scenario classification below therefore uses PER-CORPUS quantile cuts, not the pooled ones.")
    print()

    corpus_cuts: dict[str, tuple[float, float]] = {}
    print("DISTRIBUTION per corpus:")
    for corpus in sorted(by_corpus_n.keys()):
        csizes = [r["_size"] for r in sized if r["_corpus"] == corpus]
        if len(csizes) < 3:
            print(f"  {corpus:<12} n={len(csizes)} — too few runs to compute quantile cuts")
            continue
        cd = describe_distribution(csizes)
        cuts = quantile_cuts(csizes)
        corpus_cuts[corpus] = cuts
        print(f"  {corpus:<12} n={cd['n']}  min={fmt(cd['min'])}  p25={fmt(cd['p25'])}  p33={fmt(cd['p33'])}  "
              f"median={fmt(cd['median'])}  p66={fmt(cd['p66'])}  p75={fmt(cd['p75'])}  max={fmt(cd['max'])}  "
              f"-> small<={fmt(cuts[0])} medium<={fmt(cuts[1])} large>")
    print()

    for r in sized:
        cuts = corpus_cuts.get(r["_corpus"], pooled_cuts)
        r["_scenario"] = scenario_of(r["_size"], cuts)

    corpora = sorted(by_corpus_n.keys())
    scenarios = ["small", "medium", "large"]
    table_rows = []
    for corpus in corpora:
        for scenario in scenarios:
            for pipeline in PIPELINES:
                cell = [r for r in sized if r["_corpus"] == corpus and r["_scenario"] == scenario
                        and r["_pipeline"] == pipeline]
                if not cell:
                    continue
                stats = cell_stats(cell)
                table_rows.append((corpus, scenario, pipeline, stats))

    if a.json:
        print(json.dumps([{"corpus": c, "scenario": s, "pipeline": p, **st_} for c, s, p, st_ in table_rows],
                          indent=2, ensure_ascii=False))
        return

    print("PER (corpus x scenario x pipeline) CELL")
    print("-" * 100)
    hdr = (f"{'corpus':<10}{'scenario':<9}{'pipeline':<16}{'n':>5}  {'recall':>12}  "
           f"{'tok_spent_med':>14}  {'amplif_med':>11}  {'lat_ms_med':>11}  "
           f"{'jev_fallback':>13}  {'empty_ctx':>10}")
    print(hdr)
    print("-" * len(hdr))
    for corpus, scenario, pipeline, s in table_rows:
        flag = " *n<10*" if s["n"] < MIN_CELL_N else ""
        recall = f"{s['recall_mean']:.3f}(n={s['recall_n']})" if s["recall_mean"] is not None else "—"
        print(f"{corpus:<10}{scenario:<9}{pipeline:<16}{s['n']:>5}  {recall:>12}  "
              f"{fmt(s['total_tokens_spent_median']):>14}  {fmt(s['token_amplification_median']):>11}  "
              f"{fmt(s['latency_ms_median']):>11}  {s['jev_fallback_rate']:>13}  {s['empty_context_rate']:>10}{flag}")

    print()
    small_n = sum(1 for *_, s in table_rows if s["n"] < MIN_CELL_N)
    print(f"CELLS WITH n < {MIN_CELL_N}: {small_n}/{len(table_rows)} — those rows are printed but must not be")
    print("used alone to justify a threshold; treat them as directional only.")
    missing = [(c, p) for c in corpora for p in PIPELINES if by_corpus_n.get(c, 0)
               and not any(r["_corpus"] == c and r["_pipeline"] == p for r in sized)]
    if missing:
        print()
        print("MISSING (corpus, pipeline) COMBINATIONS — no runs recorded at all:")
        for c, p in missing:
            print(f"  corpus={c}  pipeline={p}")


if __name__ == "__main__":
    main()
