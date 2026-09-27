"""Deterministic pipeline audit — zero LLM tokens.

Reads benchmark.db read-only and aggregates real per-pipeline metrics:
where tokens enter, where they grow, where they could be reduced.

Usage:
    python scripts/audit_pipeline.py [--db benchmark.db] [--json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics as st
from collections import defaultdict
from pathlib import Path

PIPELINES = ["baseline", "graphify", "graphify_jev"]

# metric key -> stage label (pipeline funnel order)
FUNNEL = [
    ("documents_found", "1. retrieved (raw candidates)"),
    ("documents_deduplicated", "2. removed by dedup"),
    ("candidate_tokens_before_filter", "3. candidate tokens (pre-filter)"),
    ("documents_sent_to_jev", "4. sent to JEV"),
    ("jev_input_tokens", "5. JEV input tokens"),
    ("jev_output_tokens", "6. JEV output tokens"),
    ("documents_kept", "7. JEV kept"),
    ("documents_dropped", "8. JEV dropped"),
    ("survivors", "9. survivors"),
    ("survivor_tokens_snippets", "10. survivor tokens (snippets only)"),
    ("documents_sent_to_model", "11. docs sent to model"),
    ("context_tokens", "12. FINAL context tokens"),
    ("total_tokens_spent", "13. TOTAL tokens spent"),
    ("token_amplification", "14. token amplification (x)"),
]

LATENCY = [
    ("retrieval_latency_ms", "retrieval"),
    ("graphify_latency_ms", "graphify"),
    ("filter_latency_ms", "filter+dedup(+jev wall)"),
    ("jev_latency_ms", "jev"),
    ("full_note_latency_ms", "full-note expansion"),
    ("context_build_latency_ms", "context build"),
    ("total_latency_ms", "TOTAL"),
]

COST = [("jev_cost", "jev"), ("total_cost", "total")]


def load(db: str, mode: str = "retrieval") -> dict[str, list[dict]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out: dict[str, list[dict]] = defaultdict(list)
    q = (
        "select pipeline, metrics_json, context, sources_json from runs "
        "where mode=? and metrics_json is not null and (error is null or error='')"
    )
    for r in con.execute(q, (mode,)):
        m = json.loads(r["metrics_json"])
        m["_context_chars"] = len(r["context"] or "")
        # Back-fill the honest cost metrics for runs recorded before they existed, so historical
        # rows stay comparable instead of showing gaps.
        judge = (m.get("jev_input_tokens") or 0) + (m.get("jev_output_tokens") or 0)
        m.setdefault("judge_tokens", judge)
        ctx = m.get("context_tokens") or 0
        m.setdefault("total_tokens_spent", judge + ctx)
        if m.get("token_amplification") is None and ctx:
            m["token_amplification"] = round(m["total_tokens_spent"] / ctx, 2)
        # recall lives inside a nested dict; lift it so it can be aggregated like any metric
        exp = m.get("expected_sources_found")
        if isinstance(exp, dict) and "recall" in exp:
            m["_recall"] = exp["recall"]
        try:
            m["_n_sources"] = len(json.loads(r["sources_json"] or "[]"))
        except Exception:
            m["_n_sources"] = None
        out[r["pipeline"]].append(m)
    con.close()
    return out


def med(rows: list[dict], key: str):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(st.median(vals), 1) if vals else None


def fmt(v):
    if v is None:
        return "  —  "
    if isinstance(v, float) and v != int(v):
        return f"{v:,.1f}"
    return f"{int(v):,}"


def dup_report(db: str) -> list[tuple]:
    """Duplicate (run, source_file) pairs surviving into the candidate set."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "select r.pipeline, count(*) dup_rows, sum(c.tokens) dup_tokens from ("
        "  select run_id, source_file, count(*) n from candidates"
        "  where decision in ('keep','review') group by run_id, source_file having n>1"
        ") d join candidates c on c.run_id=d.run_id and c.source_file=d.source_file"
        " join runs r on r.run_id=d.run_id group by r.pipeline"
    ).fetchall()
    con.close()
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "benchmark.db"))
    ap.add_argument("--mode", default="retrieval")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    data = load(a.db, a.mode)
    if a.json:
        print(json.dumps({p: {k: med(r, k) for k, _ in FUNNEL + LATENCY + COST} for p, r in data.items()}, indent=2))
        return

    w = 36
    hdr = "STAGE".ljust(w) + "".join(p.ljust(16) for p in PIPELINES)
    print("=" * len(hdr))
    print(f"MEMORY GATEWAY — PIPELINE AUDIT (median, mode={a.mode})")
    print("=" * len(hdr))
    print("runs: " + ", ".join(f"{p}={len(data.get(p, []))}" for p in PIPELINES))
    print()
    print(hdr)
    print("-" * len(hdr))
    for key, label in FUNNEL:
        print(label.ljust(w) + "".join(fmt(med(data.get(p, []), key)).ljust(16) for p in PIPELINES))

    print()
    print("TOKEN GROWTH vs BASELINE")
    print("-" * len(hdr))
    base_ctx = med(data.get("baseline", []), "context_tokens")
    base_tot = med(data.get("baseline", []), "total_tokens_spent")
    print("  pipeline           final_ctx   vs base     TOTAL spent   vs base")
    for p in PIPELINES:
        ctx = med(data.get(p, []), "context_tokens")
        tot = med(data.get(p, []), "total_tokens_spent")
        d_ctx = f"{(ctx / base_ctx - 1) * 100:+.0f}%" if base_ctx and ctx else "—"
        d_tot = f"{(tot / base_tot - 1) * 100:+.0f}%" if base_tot and tot else "—"
        print(f"  {p.ljust(18)} {fmt(ctx).rjust(9)}   {d_ctx.rjust(7)}   {fmt(tot).rjust(11)}   {d_tot.rjust(7)}")
    print("  NOTE: a shrinking final context with a growing TOTAL means the pipeline is paying a")
    print("        judge more than it saves. Read both columns, never the first one alone.")

    print()
    print("QUALITY — recall of expected source (ground truth in final context)")
    print("-" * len(hdr))
    for p in PIPELINES:
        rows = [r for r in data.get(p, []) if "_recall" in r]
        if not rows:
            print(f"  {p.ljust(18)} —")
            continue
        vals = [r["_recall"] for r in rows]
        perfect = sum(1 for v in vals if v == 1.0)
        print(f"  {p.ljust(18)} mean={sum(vals) / len(vals):.3f}   perfect={perfect}/{len(vals)}")

    print()
    print("LATENCY ms (median)".ljust(w) + "".join(p.ljust(16) for p in PIPELINES))
    print("-" * len(hdr))
    for key, label in LATENCY:
        print(label.ljust(w) + "".join(fmt(med(data.get(p, []), key)).ljust(16) for p in PIPELINES))

    print()
    print("COST USD (median)".ljust(w) + "".join(p.ljust(16) for p in PIPELINES))
    print("-" * len(hdr))
    for key, label in COST:
        row = "".join(
            (f"{med(data.get(p, []), key):.6f}" if med(data.get(p, []), key) is not None else "  —  ").ljust(16)
            for p in PIPELINES
        )
        print(label.ljust(w) + row)

    print()
    print("EFFICIENCY")
    print("-" * len(hdr))
    for p in PIPELINES:
        r = data.get(p, [])
        pre, fin = med(r, "candidate_tokens_before_filter"), med(r, "context_tokens")
        snip = med(r, "survivor_tokens_snippets")
        red = f"{(1 - fin / pre) * 100:.1f}%" if pre and fin else "—"
        exp = f"{fin / snip:.1f}x" if snip and fin else "—"
        cc = med(r, "_context_chars")
        print(f"  {p.ljust(14)} reduction={red.rjust(7)}  snippet->context expansion={exp.rjust(6)}  context_chars={fmt(cc)}")

    print()
    print("DUPLICATION (same source_file kept more than once in a run)")
    print("-" * len(hdr))
    for pipeline, n, tok in dup_report(a.db):
        print(f"  {str(pipeline).ljust(14)} rows={n:<6} tokens={tok or 0:,}")


if __name__ == "__main__":
    main()
