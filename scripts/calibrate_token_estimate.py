"""Empirical token-estimator ratio from provider-reported usage (T2.1 fallback, no tokenizer needed).

Compares `model_input_tokens` (provider-reported, answer mode, generic consumer = no agent overhead)
with `prompt_tokens_estimate` (app.gateway.token_budget.estimate_tokens of the SAME prompt), both
already stored in runs.metrics_json. Reads a database passed on the command line, opened read-only
(`mode=ro`): COPY benchmark.db first and pass the copy. Never pass the live file.

    python scripts/calibrate_token_estimate.py /path/to/copy_of_benchmark.db [--json out.json]

Output groups by metrics_version (the estimator's calibration factor differs between versions) and
reports n, median/mean ratio real/estimated, stdev and p10/p90. Nothing is invented: with n=0 it says so.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from pathlib import Path


def collect(db_path: str) -> dict[str, list[float]]:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    groups: dict[str, list[float]] = {}
    try:
        for mj, agent, prov, model in con.execute(
                "SELECT metrics_json, agent, provider, model FROM runs WHERE metrics_json LIKE '%model_input_tokens%'"):
            if agent != "generic":  # full agents (hermes/claude_code/...) add system prompt + tool schemas
                continue
            try:
                m = json.loads(mj)
            except (TypeError, ValueError):
                continue
            real, est = m.get("model_input_tokens"), m.get("prompt_tokens_estimate")
            if not isinstance(real, (int, float)) or not isinstance(est, (int, float)) or real <= 0 or est <= 0:
                continue
            if m.get("agent_tokens") is not None:
                continue
            tok = m.get("consumer_model") or model or "?"
            groups.setdefault(f"tokenizer_of={tok} metrics_version={m.get('metrics_version', 'absent')}", []).append(real / est)
    finally:
        con.close()
    return groups


def summarize(ratios: list[float]) -> dict:
    s = sorted(ratios)
    n = len(s)
    q = lambda p: s[min(n - 1, int(p * (n - 1) + 0.5))]  # noqa: E731
    return {"n": n, "median": round(statistics.median(s), 4), "mean": round(statistics.fmean(s), 4),
            "stdev": round(statistics.stdev(s), 4) if n > 1 else None,
            "p10": round(q(0.10), 4), "p90": round(q(0.90), 4), "min": round(s[0], 4), "max": round(s[-1], 4)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    groups = collect(a.db)
    out = {k: summarize(v) for k, v in sorted(groups.items())}
    if not out:
        print("n=0: no runs with provider-reported input tokens + prompt estimate; nothing to calibrate.")
    for k, v in out.items():
        print(k, v)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
