"""Before/after benchmark of the Automatic Memory Optimization Layer — ZERO API calls, zero cost.

Compares, over the same questions and the same vault:
  A  before         optimizer disabled, pipeline=baseline   (exact pre-2026-09-28 behaviour)
  B  before_graph   optimizer disabled, pipeline=graphify
  C  after          optimizer enabled,  pipeline=auto        (what every caller now gets)
  D  after_graph    optimizer enabled,  pipeline=graphify
plus the consumer-side transport cost of one MCP call (tool schemas + response JSON), before/after.

Quality signals (ground truth from the benchmark file):
  recall          expected source among delivered sources (answerable questions only)
  fact_in_context the corpus manifest's buried fact token is literally present in the context
                  (synthetic corpus only; the strongest "the model can answer" signal we have)
  malicious_unflagged  a known-malicious note delivered WITHOUT the injection warning

The judge pipelines are NOT run here (they cost money and were measured on 2026-09-27; see
reports/opt_stack_FINAL.json). Run:  python scripts/bench_optimizer.py [--vault PATH --questions PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("MEMORY_GATEWAY_VAULT", str(PROJECT_ROOT / "data" / "synthetic_vault"))

from config.benchmark import BenchmarkConfig  # noqa: E402
from config.optimizer import OptimizerConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.database.db import Database  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.gateway.token_budget import estimate_tokens  # noqa: E402
from app.retrieval.graphify_hybrid import GraphIndex  # noqa: E402

ARMS = {
    "A_before_baseline": (False, "baseline"),
    "B_before_graphify": (False, "graphify"),
    "C_after_auto": (True, "auto"),
    "D_after_graphify": (True, "graphify"),
}


def make_gw(vault: Path, enabled: bool) -> MemoryGateway:
    rc = RetrievalConfig(vault_path=vault)
    # benchmark profile: every cache off, so each arm pays its own full path (no warm-arm bias)
    bc = BenchmarkConfig(db_path=str(Path(tempfile.mkdtemp()) / "b.db"), profile="benchmark")
    ocfg = OptimizerConfig() if enabled else OptimizerConfig.disabled()
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=ocfg)
    g = vault / "graphify-out" / "graph.json"
    if g.exists():
        gw.graph_index = GraphIndex(g)
    gw.warm()
    return gw


def run_arm(gw, pipeline, qs, manifest) -> dict:
    facts = {f["path"]: f["token"] for f in (manifest or {}).get("facts", [])}
    malicious = set((manifest or {}).get("injection_notes", {}).get("malicious", []))
    rows = []
    for q in qs:
        t0 = time.perf_counter()
        r = gw.search(q["question"], pipeline, 10, persist=False)
        lat = (time.perf_counter() - t0) * 1000
        files = [s.file for s in r.sources]
        exp = q.get("expected_sources") or []
        row = {"qid": q["id"], "answerable": q.get("answerable", True), "ctx": r.metrics["context_tokens"],
               "docs": len(files), "lat": lat, "pipeline": r.pipeline,
               "complexity": r.metrics.get("query_complexity")}
        if row["answerable"] and exp:
            row["recall"] = sum(e in files for e in exp) / len(exp)
            toks = [facts[e] for e in exp if e in facts]
            if toks:
                row["fact"] = all(t.lower() in r.context.lower() for t in toks)
        # malicious note delivered without the warning attribute on its block
        unflagged = 0
        for f in files:
            if f in malicious:
                blk = r.context.split(f'<note source="{f}"', 1)[1].split(">", 1)[0]
                unflagged += "possible-prompt-injection" not in blk
        row["mal_delivered"] = sum(f in malicious for f in files)
        row["mal_unflagged"] = unflagged
        rows.append(row)
    return summarize(rows)


def summarize(rows) -> dict:
    ans = [r for r in rows if "recall" in r]
    fact = [r["fact"] for r in rows if "fact" in r]
    ctx = [r["ctx"] for r in rows]
    return {
        "questions": len(rows),
        "context_tokens_total": sum(ctx),
        "context_tokens_mean": round(statistics.mean(ctx), 1),
        "context_tokens_median": statistics.median(ctx),
        "docs_mean": round(statistics.mean(r["docs"] for r in rows), 2),
        "recall_mean": round(statistics.mean(r["recall"] for r in ans), 4) if ans else None,
        "recall_full": sum(r["recall"] == 1.0 for r in ans),
        "answerable": len(ans),
        "fact_in_context": f"{sum(fact)}/{len(fact)}" if fact else None,
        "malicious_delivered": sum(r["mal_delivered"] for r in rows),
        "malicious_unflagged": sum(r["mal_unflagged"] for r in rows),
        "latency_ms_median": round(statistics.median(r["lat"] for r in rows), 1),
        "pipelines_used": dict(sorted({p: sum(r["pipeline"] == p for r in rows)
                                       for p in {r["pipeline"] for r in rows}}.items())),
        "_rows": rows,
    }


def mcp_transport(vault: Path, q: str) -> dict:
    """Tokens an MCP consumer pays per call: tool schemas (every turn) + response JSON."""
    import asyncio
    import importlib

    out = {}
    for label, toolset, response, enabled in (("before", "full", "full", False),
                                              ("after", "minimal", "compact", True)):
        os.environ["MG_MCP_TOOLSET"] = toolset
        os.environ["MG_MCP_RESPONSE"] = response
        from app.mcp import server as mod
        mod = importlib.reload(mod)
        mod._gateway = make_gw(vault, enabled)
        tools = asyncio.run(mod.server.list_tools())
        schema = sum(estimate_tokens(json.dumps(t.model_dump(exclude_none=True), ensure_ascii=False))
                     for t in tools)
        pipe = "baseline" if label == "before" else "auto"
        resp = mod._search(q, pipe, 10)
        out[label] = {"tools": len(tools), "schema_tokens_per_turn": schema,
                      "response_tokens": estimate_tokens(json.dumps(resp, ensure_ascii=False)),
                      "context_tokens": estimate_tokens(resp["context"])}
    os.environ.pop("MG_MCP_TOOLSET", None)
    os.environ.pop("MG_MCP_RESPONSE", None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=str(PROJECT_ROOT / "data" / "synthetic_vault"))
    ap.add_argument("--questions", default=str(PROJECT_ROOT / "benchmark" / "synthetic_questions.json"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--rows", action="store_true", help="keep per-question rows in the JSON output")
    a = ap.parse_args()
    vault = Path(a.vault).resolve()
    qs = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    mpath = vault / "MANIFEST.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else None

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "vault_notes": None,
              "questions": len(qs), "api_calls": 0, "arms": {}}
    gws = {True: make_gw(vault, True), False: make_gw(vault, False)}
    report["vault_notes"] = gws[True].baseline.files_indexed
    for name, (enabled, pipe) in ARMS.items():
        report["arms"][name] = run_arm(gws[enabled], pipe, qs, manifest)
    report["mcp_transport"] = mcp_transport(vault, qs[0]["question"])

    b, c = report["arms"]["A_before_baseline"], report["arms"]["C_after_auto"]
    report["delta_A_to_C"] = {
        "context_tokens_saved_pct": round(1 - c["context_tokens_total"] / b["context_tokens_total"], 4),
        "recall_delta": round((c["recall_mean"] or 0) - (b["recall_mean"] or 0), 4),
        "fact_in_context": f'{b["fact_in_context"]} -> {c["fact_in_context"]}',
        "malicious_unflagged": f'{b["malicious_unflagged"]} -> {c["malicious_unflagged"]}',
    }
    regress = [(x["qid"], x.get("recall"), y.get("recall")) for x, y in zip(b["_rows"], c["_rows"])
               if (y.get("recall") or 0) < (x.get("recall") or 0) or (x.get("fact") and not y.get("fact"))]
    report["delta_A_to_C"]["questions_regressed"] = regress
    if not a.rows:
        for arm in report["arms"].values():
            arm.pop("_rows", None)

    print(json.dumps({k: v for k, v in report.items()}, ensure_ascii=False, indent=1, default=str))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
