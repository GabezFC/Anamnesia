#!/usr/bin/env python3
"""Memory benchmark: what the M3 memory layer (provenance, temporality, consistency) costs and what
it does NOT break. ZERO API calls, ZERO cost, read-only on every corpus.

Same questions, same ground truth and same summarizer as scripts/bench_optimizer.py
(`run_arm`'s summarizer is imported, not re-implemented); the difference is that this script also
captures the per-run MEMORY metrics and compares four arms per corpus:

    A_before     optimizer OFF, pipeline=baseline            exact pre-2026-09-28 behaviour
    B_flags_off  optimizer ON, M3 flags OFF                   isolates the M3 layer alone
    C_flags_on   optimizer ON, M3 flags ON                    the new default
    D_frozen_jev optimizer ON, M3 flags ON, pipeline=graphify_jev -- MUST equal B_flags_off's context:
                  the frozen reference pipeline never receives provenance, temporal demotion or
                  conflict marking (M3 design rule 4)

Corpora:
    synthetic  data/synthetic_vault + benchmark/synthetic_questions.json (facts/malicious manifest)
    real       the configured vault (READ ONLY) + its own questions.json

Usage:
    python scripts/bench_memory.py --real-vault PATH --real-questions PATH [--db PATH] --audit-real
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("MEMORY_GATEWAY_VAULT", str(PROJECT_ROOT / "data" / "synthetic_vault"))

from config.benchmark import BenchmarkConfig  # noqa: E402
from config.optimizer import OptimizerConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.gateway.optimizer import MemoryOptimizer  # noqa: E402
from app.retrieval.graphify_hybrid import GraphIndex  # noqa: E402
from scripts.bench_optimizer import summarize  # noqa: E402
from app.services.provenance import wants_history  # noqa: E402

MEMORY_FLAGS = ("provenance", "temporal_demote", "conflict_check")
MEMORY_METRIC_KEYS = ("memory_historical_total", "memory_historical_demoted",
                      "memory_historical_excluded", "memory_history_requested",
                      "memory_conflicts_detected", "memory_conflict_same_title",
                      "memory_conflict_overlap", "provenance_tokens", "provenance_lines",
                      "provenance_on_flagged")


def with_flags(cfg: OptimizerConfig, on: bool) -> OptimizerConfig:
    return cfg.with_(**{f: on for f in MEMORY_FLAGS})


def make_gw(vault: Path, cfg: OptimizerConfig) -> MemoryGateway:
    """Like scripts/bench_optimizer.make_gw but takes the WHOLE config, not just an on/off flag —
    a benchmark arm must be able to turn individual stages off without a second gateway."""
    import tempfile
    rc = RetrievalConfig(vault_path=vault)
    bc = BenchmarkConfig(db_path=str(Path(tempfile.mkdtemp()) / "b.db"), profile="benchmark")
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=cfg)
    g = vault / "graphify-out" / "graph.json"
    if g.exists():
        gw.graph_index = GraphIndex(g)
    gw.warm()
    return gw


def run_arm(gw, pipeline: str, qs: list[dict], manifest: dict | None, keep_rows: bool) -> dict:
    """bench_optimizer.run_arm, plus the M3 metrics of every run. Deterministic, no model call."""
    facts = {f["path"]: f["token"] for f in (manifest or {}).get("facts", [])}
    malicious = set((manifest or {}).get("injection_notes", {}).get("malicious", []))
    rows = []
    for q in qs:
        t0 = time.perf_counter()
        r = gw.search(q["question"], pipeline, 10, persist=False)
        lat = (time.perf_counter() - t0) * 1000
        files = [s.file for s in r.sources]
        exp = q.get("expected_sources") or []
        row = {"qid": q["id"], "answerable": q.get("answerable", True),
               "ctx": r.metrics["context_tokens"], "docs": len(files), "lat": lat,
               "pipeline": r.pipeline, "complexity": r.metrics.get("query_complexity")}
        if row["answerable"] and exp:
            row["recall"] = sum(e in files for e in exp) / len(exp)
            toks = [facts[e] for e in exp if e in facts]
            if toks:
                row["fact"] = all(t.lower() in r.context.lower() for t in toks)
        unflagged = 0
        for f in files:
            if f in malicious:
                blk = r.context.split(f'<note source="{f}"', 1)[1].split(">", 1)[0]
                unflagged += "possible-prompt-injection" not in blk
        row["mal_delivered"] = sum(f in malicious for f in files)
        row["mal_unflagged"] = unflagged
        row.update({k: r.metrics.get(k) for k in MEMORY_METRIC_KEYS})
        rows.append(row)
    out = summarize(rows)
    out["memory_metrics"] = {k: sum(int(r.get(k) or 0) for r in rows) for k in MEMORY_METRIC_KEYS}
    out["memory_metrics"]["questions_with_history_requested"] = sum(
        1 for r in rows if r.get("memory_history_requested"))
    out["memory_metrics"]["questions_with_conflicts"] = sum(
        1 for r in rows if (r.get("memory_conflicts_detected") or 0) > 0)
    out["memory_metrics"]["provenance_tokens_mean_per_question"] = (
        round(out["memory_metrics"]["provenance_tokens"] / len(rows), 2) if rows else None)
    # `_rows` stays here on purpose: run_corpus needs it to find the questions that regressed
    # (an empty _rows would silently report "0 regressões"). It is dropped at the very end.
    return out


def frozen_parity(gw, qs: list[dict], on_cfg: OptimizerConfig, off_cfg: OptimizerConfig,
                  limit: int = 12) -> dict:
    """Proof that the M3 layer is a NO-OP for the frozen pipeline `graphify_jev`.

    The paid judge is never called: the same candidates are pushed through the layer twice with the
    SAME `graphify_jev` plan, once with the M3 flags on and once with them off. If the frozen
    pipeline were touched, the candidate scores, the delivered context or the emitted metrics would
    differ. (The baseline plan is not comparable: it applies adaptive cut, which is a pre-existing
    difference between free and judge pipelines, not an M3 effect.)
    """
    import copy
    from app.gateway.optimizer import Plan
    from app.services.query_fp import classify
    opt_on, opt_off = MemoryOptimizer(on_cfg), MemoryOptimizer(off_cfg)
    opt_on.mark_built(gw.vault.fingerprint())
    opt_off.mark_built(gw.vault.fingerprint())
    same_context = same_scores = 0
    memory_metrics_on_jev = prov_lines_on_jev = 0
    checked = 0
    m_on: dict = {}
    out_on: list = []
    for q in qs[:limit]:
        try:
            cands = gw.retrieve(q["question"], "baseline")
        except Exception:  # noqa: BLE001
            continue
        if not cands:
            continue
        checked += 1
        profile = classify(q["question"])
        jev_plan = Plan("graphify_jev", "graphify_jev", profile, "explicit")
        out_on, m_on = opt_on.post_filter(copy.deepcopy(cands), jev_plan, gw=gw, query=q["question"])
        out_off, m_off = opt_off.post_filter(copy.deepcopy(cands), jev_plan, gw=gw, query=q["question"])
        if ([(c.candidate_id, round(c.score, 9)) for c in out_on]
                == [(c.candidate_id, round(c.score, 9)) for c in out_off]):
            same_scores += 1
        # The gateway is what skips the frozen pipeline (app/gateway/memory_gateway.py
        # `provenance_for`), so the "on" arm uses exactly the path a graphify_jev request takes.
        ctx_on = gw.build_context(out_on, provenance=gw.provenance_for(out_on, "graphify_jev")[0])[0]
        ctx_off = gw.build_context(out_off)[0]
        if ctx_on == ctx_off:
            same_context += 1
        memory_metrics_on_jev += sum(1 for k in m_on if k.startswith("memory_"))
        prov_lines_on_jev += len(gw.provenance_for(out_on, "graphify_jev")[0])
    return {"questions_checked": checked,
            "candidates_identical_on_vs_off": same_scores,
            "context_identical_on_vs_off": same_context,
            "memory_metrics_emitted_on_jev": memory_metrics_on_jev,
            "provenance_lines_on_jev": prov_lines_on_jev,
            "memory_metrics_keys_on_jev": sorted(k for k in m_on if k.startswith("memory_"))}


DELTA_KEYS = ("context_tokens_total", "context_tokens_mean", "context_tokens_median", "recall_mean",
              "recall_full", "answerable", "malicious_unflagged", "malicious_delivered",
              "latency_ms_median", "docs_mean")


def delta(before: dict, after: dict) -> dict:
    """Differences of measured numbers only — never a placeholder."""
    out: dict = {}
    for k in DELTA_KEYS:
        if before.get(k) is None or after.get(k) is None:
            continue
        out[k] = round(after[k] - before[k], 4)
    if before.get("fact_in_context") or after.get("fact_in_context"):
        out["fact_in_context"] = f'{before.get("fact_in_context")} -> {after.get("fact_in_context")}'
    return out


def regressed(before: dict, after: dict) -> list:
    """Questions that lost recall or their fact token when the M3 flags were on."""
    b_rows = {r["qid"]: r for r in (before.get("_rows") or [])}
    a_rows = {r["qid"]: r for r in (after.get("_rows") or [])}
    out = []
    for qid, a in a_rows.items():
        b = b_rows.get(qid)
        if not b:
            continue
        if (a.get("recall") or 0) < (b.get("recall") or 0) or (b.get("fact") and not a.get("fact")):
            out.append({"qid": qid, "recall": [b.get("recall"), a.get("recall")],
                        "fact": [b.get("fact"), a.get("fact")]})
    return out


def run_corpus(vault: Path, questions: Path, questions_label: str, keep_rows: bool) -> dict:
    qs = json.loads(questions.read_text(encoding="utf-8"))
    manifest_path = vault / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    base = OptimizerConfig()
    off, on = with_flags(base, False), with_flags(base, True)
    # D exists to settle ONE question with data instead of opinion: does "strict history" (drop
    # historical notes unless the query asks for history) cost recall and facts?
    strict = on.with_(historical_exclude=True)
    gws = {
        "A_before": make_gw(vault, OptimizerConfig.disabled()),
        "B_flags_off": make_gw(vault, off),
        "C_flags_on": make_gw(vault, on),
        "D_history_strict": make_gw(vault, strict),
    }
    out: dict = {"vault": str(vault), "vault_notes": gws["C_flags_on"].baseline.files_indexed,
                 "questions": len(qs), "questions_file": questions_label,
                 "answerable_questions": sum(1 for q in qs if q.get("answerable", True)),
                 "manifest": bool(manifest), "api_calls": 0, "arms": {}}
    for key, pipe in (("A_before", "baseline"), ("B_flags_off", "baseline"),
                      ("C_flags_on", "baseline"), ("D_history_strict", "baseline")):
        t0 = time.perf_counter()
        res = run_arm(gws[key], pipe, qs, manifest, keep_rows)
        res["wall_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out["arms"][key] = res
    out["delta_A_to_C"] = delta(out["arms"]["A_before"], out["arms"]["C_flags_on"])
    out["delta_B_to_C"] = delta(out["arms"]["B_flags_off"], out["arms"]["C_flags_on"])
    out["questions_regressed_B_to_C"] = regressed(out["arms"]["B_flags_off"], out["arms"]["C_flags_on"])
    out["delta_C_to_D_strict_history"] = delta(out["arms"]["C_flags_on"],
                                               out["arms"]["D_history_strict"])
    out["questions_regressed_C_to_D"] = regressed(out["arms"]["C_flags_on"],
                                                   out["arms"]["D_history_strict"])
    out["frozen_pipeline_parity"] = frozen_parity(gws["C_flags_on"], qs, on, off)
    out["history_questions_in_corpus"] = sum(1 for q in qs if wants_history(q["question"]))
    out["strict_history_verdict"] = {
        "recall_mean": [out["arms"]["C_flags_on"]["recall_mean"],
                        out["arms"]["D_history_strict"]["recall_mean"]],
        "fact_in_context": [out["arms"]["C_flags_on"]["fact_in_context"],
                            out["arms"]["D_history_strict"]["fact_in_context"]],
        "questions_lost_recall": len(out["questions_regressed_C_to_D"]),
    }
    if not keep_rows:
        for arm in out["arms"].values():
            arm.pop("_rows", None)
    return out


def audit_vault(vault: Path, out_path: Path, db_path: Path | None) -> dict:
    """Run the memory audit and persist ONLY counts — no line of anybody's notes."""
    from app.services.memory_audit import MemoryAuditor
    from config.retrieval import RetrievalConfig
    # Same exclusions as the CLI and the REST route, so the persisted report describes exactly the
    # notes a search can reach.
    report = MemoryAuditor(vault, db_path=db_path,
                           excluded_dirs=RetrievalConfig().excluded_dirs).audit()
    payload = report.counts_only()
    payload["corpus"] = "real_vault"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PROJECT_ROOT / "reports" / "memory_benchmark_2026-10-01.json"))
    ap.add_argument("--real-vault", default="", help="vault real (READ ONLY); default: só sintético")
    ap.add_argument("--real-questions", default="")
    ap.add_argument("--audit-real", action="store_true",
                    help="roda memory-audit no vault real e grava SÓ contagens em --audit-out")
    ap.add_argument("--audit-out", default=str(PROJECT_ROOT / "reports" / "memory_audit_2026-10-01.json"))
    ap.add_argument("--db", default="", help="benchmark.db (mode=ro) para hot/warm/cold no audit")
    ap.add_argument("--rows", action="store_true", help="mantém as linhas por pergunta no JSON")
    args = ap.parse_args()

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "note_content_included": False, "corpora": {}}
    syn = PROJECT_ROOT / "data" / "synthetic_vault"
    report["corpora"]["synthetic"] = run_corpus(
        syn, PROJECT_ROOT / "benchmark" / "synthetic_questions.json", "synthetic_questions.json",
        args.rows)

    real = Path(args.real_vault).expanduser() if args.real_vault else None
    if real and real.is_dir():
        rq = Path(args.real_questions) if args.real_questions else real / "questions.json"
        if rq.is_file():
            report["corpora"]["real"] = run_corpus(real.resolve(), rq, rq.name, args.rows)
        else:
            report["corpora"]["real"] = {"skipped": f"questions file not found: {rq}"}
        if args.audit_real:
            report["real_vault_audit"] = audit_vault(real.resolve(), Path(args.audit_out),
                                                    Path(args.db) if args.db else None)
    else:
            report["corpora"]["real"] = {"skipped": "no real vault given (--real-vault)"}


    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for name, corpus in report["corpora"].items():
        if "arms" not in corpus:
            print(f"[{name}] {corpus.get('skipped')}")
            continue
        parity = corpus["frozen_pipeline_parity"]
        print(f"[{name}] vault={corpus['vault']} notas={corpus['vault_notes']} "
              f"perguntas={corpus['questions']} regressões={len(corpus['questions_regressed_B_to_C'])} "
              f"jev_congelado: contexto_idêntico={parity['context_identical_on_vs_off']}/"
              f"{parity['questions_checked']} métricas_memória={parity['memory_metrics_emitted_on_jev']}")
        for key, res in corpus["arms"].items():
            if "error" in res:
                print(f"   {key:<13} ERROR {res['error'][:80]}")
                continue
            mm = res.get("memory_metrics", {})
            print(f"   {key:<13} ctx={res['context_tokens_total']:>7} "
                  f"recall={res['recall_mean']} facts={res['fact_in_context']} "
                  f"mal_unflagged={res['malicious_unflagged']} lat_med={res['latency_ms_median']} "
                  f"prov_tok={mm.get('provenance_tokens')} hist_demoted={mm.get('memory_historical_demoted')} "
                  f"conflicts={mm.get('memory_conflicts_detected')}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()