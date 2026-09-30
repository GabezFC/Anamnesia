"""Measure the two no-model optional stages (sentence_dedup_mmr, spotlight_nonce — proposta
2026-09-28 §1.4/§5.5) over REAL final contexts already recorded in benchmark.db.

READ ONLY: opens benchmark.db with `mode=ro`, never writes anything. The stage functions
themselves (app/retrieval/optional_stages.py) normally run BEFORE ModelContextBuilder assembles the
final `<note>` blocks, on a live pipeline's candidates; this script reconstructs a close
approximation by parsing the ALREADY-BUILT `context` column back into one pseudo-candidate per
`<note>` block, so the measurement uses real vault text instead of synthetic examples.

Usage:
    python scripts/measure_optional_stages.py [--limit N] [--db PATH]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.gateway.token_budget import estimate_tokens  # noqa: E402
from app.retrieval.optional_stages import sentence_dedup_mmr, spotlight_nonce  # noqa: E402
from app.schemas.models import Candidate  # noqa: E402
from config.optimization import OptionalStagesConfig  # noqa: E402

_NOTE = re.compile(r'<note source="([^"]+)"[^>]*>\n(.*?)\n</note>', re.S)

DEFAULT_DB = ROOT / "benchmark.db"


def load_runs(db_path: Path, limit: int) -> list[tuple[str, str, str]]:
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT run_id, query, context FROM runs "
            "WHERE context IS NOT NULL AND length(context) > 400 AND warmup = 0 "
            "ORDER BY created_at DESC LIMIT ?", (limit,))
        return cur.fetchall()
    finally:
        con.close()


def context_to_candidates(context: str) -> list[Candidate]:
    cands = []
    for i, (source, body) in enumerate(_NOTE.findall(context)):
        cands.append(Candidate(candidate_id=f"c{i}", source_file=source, section="", snippet=body,
                               score=1.0 - i * 0.01, content_hash=f"h{i}:{hash(body) & 0xffffffff}"))
    return cands


def measure(runs: list[tuple[str, str, str]]) -> None:
    dedup_cfg = OptionalStagesConfig()
    spot_cfg = OptionalStagesConfig(spotlight_nonce_mode="hash")

    dedup_tokens_before = dedup_tokens_after = 0
    dedup_latencies = []
    dedup_sentences_dropped = 0
    dedup_runs_changed = 0

    spot_tokens_before = spot_tokens_after = 0
    spot_latencies = []

    considered = 0
    for run_id, query, context in runs:
        cands = context_to_candidates(context)
        if not cands:
            continue
        considered += 1

        dedup_cands = [Candidate(**{**c.to_dict()}) for c in cands]
        before = sum(estimate_tokens(c.snippet) for c in dedup_cands)
        t0 = time.perf_counter()
        m = sentence_dedup_mmr(query, dedup_cands, {}, dedup_cfg)
        dedup_latencies.append((time.perf_counter() - t0) * 1000)
        after = sum(estimate_tokens(c.snippet) for c in dedup_cands)
        dedup_tokens_before += before
        dedup_tokens_after += after
        dedup_sentences_dropped += m.get("stage_sentence_dedup_mmr_sentences_dropped", 0)
        if after != before:
            dedup_runs_changed += 1

        spot_cands = [Candidate(**{**c.to_dict()}) for c in cands]
        before_s = sum(estimate_tokens(c.snippet) for c in spot_cands)
        t0 = time.perf_counter()
        spotlight_nonce(query, spot_cands, {}, spot_cfg)
        spot_latencies.append((time.perf_counter() - t0) * 1000)
        after_s = sum(estimate_tokens(c.snippet) for c in spot_cands)
        spot_tokens_before += before_s
        spot_tokens_after += after_s

    print(f"Runs considered: {considered} (of {len(runs)} fetched)")
    print()
    print("== sentence_dedup_mmr ==")
    print(f"  tokens before: {dedup_tokens_before}")
    print(f"  tokens after:  {dedup_tokens_after}")
    saved = dedup_tokens_before - dedup_tokens_after
    pct = round(100 * saved / dedup_tokens_before, 2) if dedup_tokens_before else 0.0
    print(f"  tokens saved:  {saved} ({pct}%)")
    print(f"  runs changed:  {dedup_runs_changed}/{considered}")
    print(f"  sentences dropped (total): {dedup_sentences_dropped}")
    if dedup_latencies:
        print(f"  latency ms: mean={statistics.mean(dedup_latencies):.3f} "
              f"p50={statistics.median(dedup_latencies):.3f} max={max(dedup_latencies):.3f}")
    print()
    print("== spotlight_nonce (mode=hash) ==")
    print(f"  tokens before: {spot_tokens_before}")
    print(f"  tokens after:  {spot_tokens_after}")
    added = spot_tokens_after - spot_tokens_before
    pct2 = round(100 * added / spot_tokens_before, 2) if spot_tokens_before else 0.0
    print(f"  tokens added (delimiter overhead): {added} ({pct2}%)")
    if spot_latencies:
        print(f"  latency ms: mean={statistics.mean(spot_latencies):.3f} "
              f"p50={statistics.median(spot_latencies):.3f} max={max(spot_latencies):.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    if not args.db.exists():
        print(f"benchmark.db não encontrado em {args.db}", file=sys.stderr)
        raise SystemExit(1)
    runs = load_runs(args.db, args.limit)
    if not runs:
        print("nenhum run com contexto encontrado", file=sys.stderr)
        raise SystemExit(1)
    measure(runs)


if __name__ == "__main__":
    main()
