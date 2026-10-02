"""Benchmark of the 6 optional retrieval stages (app/retrieval/optional_stages.py) over the SAME
questions, each arm isolated, against the mandatory baseline.

  synthetic corpus  120 queries, NO JEV, zero cost: pipeline `graphify` (optimizer ON) is the baseline.
                    Quality signals come from the corpus manifest (recall, fact_in_context,
                    malicious_unflagged / malicious_unprotected).
  real vault        12 questions (10 answerable + 2 without an answer) on `graphify_jev_opt` (PAID JEV).
                    The baseline arm runs FIRST and pays for the judgements; every later arm reuses them
                    through the JEV layered cache (same content_hash), so the stage is the only variable.
                    No manifest exists, so fact_in_context is replaced by `hint_coverage`, a PROXY: the
                    share of distinctive tokens (backticks, digit-bearing tokens, identifiers) of the
                    question's `answer_hint` that appear in the delivered context.

Arms: baseline, each of the 6 stages alone, then the combinations dedup+rerank(best),
dedup+compress(best), compress+rerank, dedup+compress+rerank (best picked from the isolated arms).

Per arm: tokens (jev in/out, context, total, amplification, savings vs baseline), docs retrieved /
after filter / in final context, latency (total, stage, load), cost, recall, precision, MRR, facts,
malicious, model calls, cache hits/misses, RAM, VRAM, model disk size, cold-start. Anything the platform
cannot provide is null ("NÃO MEDIDO"), never estimated.

Run with a SEPARATE venv that has torch + the optional libraries (requirements-optional.txt):
    <bench-venv>/Scripts/python.exe scripts/bench_stages.py --corpus both \
        --vault <PATH_TO_REAL_VAULT> --real-questions <PATH_TO>/questions.json
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import re
import statistics
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("MEMORY_GATEWAY_VAULT", str(PROJECT_ROOT / "data" / "synthetic_vault"))

import config.local_settings as _local_settings  # noqa: E402

# Never let a developer's config/local_settings.json toggle a stage behind the benchmark's back.
_local_settings.get_optional_stages = lambda: {}

from app.database.db import Database  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.retrieval import optional_stages as OS  # noqa: E402
from app.retrieval.graphify_hybrid import GraphIndex  # noqa: E402
from config.benchmark import BenchmarkConfig  # noqa: E402
from config.optimization import APPROVED_STAGES, OPTIONAL_STAGE_NAMES, OptionalStagesConfig  # noqa: E402
from config.optimizer import OptimizerConfig  # noqa: E402
from config.retrieval import RetrievalConfig  # noqa: E402

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None
try:
    import torch
except ImportError:  # pragma: no cover
    torch = None

MODEL_REPOS = {"llmlingua2": OS.LLMLINGUA2_MODEL, "provence": OS.PROVENCE_MODEL,
               "bge_reranker_v2_m3": OS.BGE_MODEL, "mxbai_rerank_base_v2": OS.MXBAI_MODEL}
RERANKERS = ("bge_reranker_v2_m3", "mxbai_rerank_base_v2")
COMPRESSORS = ("llmlingua2", "provence")
NA = None  # "NÃO MEDIDO"


# --------------------------------------------------------------------------------------------------
# resources
# --------------------------------------------------------------------------------------------------
def rss_mb() -> float | None:
    return round(psutil.Process().memory_info().rss / 2**20, 1) if psutil else NA


def vram_peak_mb() -> float | None:
    if torch is None or not torch.cuda.is_available():
        return NA
    return round(torch.cuda.max_memory_allocated() / 2**20, 1)


def reset_arm_state() -> None:
    OS.release_models()
    OS.clear_rerank_cache()
    gc.collect()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def model_disk_mb(repo: str) -> float | None:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    blobs = hub / f"models--{repo.replace('/', '--')}" / "blobs"
    if not blobs.exists():
        return NA
    return round(sum(f.stat().st_size for f in blobs.iterdir() if f.is_file()) / 2**20, 1)


# --------------------------------------------------------------------------------------------------
# quality helpers
# --------------------------------------------------------------------------------------------------
_HINT_TOKEN = re.compile(r"`([^`]+)`|(\b[\w./:-]*\d[\w./:-]*\b)|(\b\w*[_][\w_]+\b)")


def hint_tokens(hint: str) -> list[str]:
    """Distinctive tokens of an answer_hint (PROXY for fact_in_context on the real vault)."""
    out: list[str] = []
    for a, b, c in _HINT_TOKEN.findall(hint or ""):
        t = (a or b or c).strip(" .,;:()").lower()
        if len(t) >= 2 and t not in out:
            out.append(t)
    return out


def hint_coverage(hint: str, context: str) -> float | None:
    toks = hint_tokens(hint)
    if not toks:
        return NA
    ctx = context.lower()
    return sum(t in ctx for t in toks) / len(toks)


def note_block(context: str, source: str) -> str:
    parts = context.split(f'<note source="{source}"', 1)
    return parts[1].split("</note>", 1)[0] if len(parts) == 2 else ""


def question_row(q: dict, r, manifest: dict | None, real: bool) -> dict:
    m = r.metrics
    files = [s.file for s in r.sources]
    exp = q.get("expected_sources") or []
    facts = {f["path"]: f["token"] for f in (manifest or {}).get("facts", [])}
    malicious = set((manifest or {}).get("injection_notes", {}).get("malicious", []))
    stage_lat = sum(v for k, v in m.items() if k.startswith("stage_") and k.endswith("_latency_ms"))
    load_ms = sum(v for k, v in m.items() if k.startswith("stage_") and k.endswith("_load_ms"))
    row = {
        "qid": q["id"], "answerable": q.get("answerable", True), "ctx": m["context_tokens"],
        "jev_in": m.get("jev_input_tokens"), "jev_out": m.get("jev_output_tokens"),
        "judge_tokens": m.get("judge_tokens", 0), "total_tokens_spent": m["total_tokens_spent"],
        "jev_cost": m.get("jev_cost"), "jev_cache_hits": m.get("jev_cache_hits", 0),
        "found": m.get("documents_found"), "after_filter": m.get("survivors"),
        "final_docs": len(files), "lat": m["total_latency_ms"], "stage_lat": round(stage_lat, 1),
        "load_ms": round(load_ms, 1), "pipeline": r.pipeline,
        "skipped": m.get("optional_stages_skipped", []), "errors": m.get("optional_stages_errors", []),
        "model_calls": sum(v for k, v in m.items() if k.startswith("stage_") and k.endswith("_model_calls")),
        "cache_hits": sum(v for k, v in m.items() if k.startswith("stage_") and k.endswith("_cache_hits")),
        "cache_misses": sum(v for k, v in m.items() if k.startswith("stage_") and k.endswith("_cache_misses")),
        "stage_tokens_saved": sum(v for k, v in m.items() if k.startswith("stage_") and k.endswith("_tokens_saved")),
        "empty": m["context_tokens"] == 0,
    }
    if row["answerable"] and exp:
        row["recall"] = sum(e in files for e in exp) / len(exp)
        row["precision"] = (sum(f in exp for f in files) / len(files)) if files else 0.0
        row["p_at_3"] = (sum(f in exp for f in files[:3]) / min(3, len(files))) if files else 0.0
        ranks = [files.index(e) + 1 for e in exp if e in files]
        row["mrr"] = 1.0 / min(ranks) if ranks else 0.0
        toks = [facts[e] for e in exp if e in facts]
        if toks:
            row["fact"] = all(t.lower() in r.context.lower() for t in toks)
        if real:
            row["hint_cov"] = hint_coverage(q.get("answer_hint", ""), r.context)
    mal = [f for f in files if f in malicious]
    unflagged = unprotected = 0
    for f in mal:
        blk = note_block(r.context, f)
        flagged = "possible-prompt-injection" in blk.split(">", 1)[0] or "possible-prompt-injection" in blk[:200]
        unflagged += not flagged
        unprotected += not (flagged or "<<<SPOTLIGHT:" in blk)
    row.update({"mal_delivered": len(mal), "mal_unflagged": unflagged, "mal_unprotected": unprotected})
    return row


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else NA


def summarize(name: str, stages: tuple[str, ...], rows: list[dict], wall_s: float) -> dict:
    ans = [r for r in rows if "recall" in r]
    fact = [r["fact"] for r in rows if "fact" in r]
    jc = [r["jev_cost"] for r in rows]
    cold = sum(r["load_ms"] for r in rows)
    return {
        "arm": name, "stages": list(stages), "questions": len(rows), "answerable": len(ans),
        "wall_s": round(wall_s, 1),
        "tokens": {
            "context_total": sum(r["ctx"] for r in rows),
            "context_mean": round(statistics.mean(r["ctx"] for r in rows), 1),
            "jev_input_paid": sum(r["jev_in"] or 0 for r in rows),
            "jev_output_paid": sum(r["jev_out"] or 0 for r in rows),
            "judge_paid": sum(r["judge_tokens"] for r in rows),
            "total_spent_measured": sum(r["total_tokens_spent"] for r in rows),
            "stage_tokens_saved_in_stage": sum(r["stage_tokens_saved"] for r in rows),
        },
        "docs": {"retrieved_mean": _mean(r["found"] for r in rows), "after_filter_mean": _mean(r["after_filter"] for r in rows),
                 "final_mean": _mean(r["final_docs"] for r in rows)},
        "latency_ms": {"total_mean": round(statistics.mean(r["lat"] for r in rows), 1),
                       "total_median": round(statistics.median(r["lat"] for r in rows), 1),
                       "total_mean_excl_load": round(statistics.mean(r["lat"] - r["load_ms"] for r in rows), 1),
                       "stage_mean": round(statistics.mean(r["stage_lat"] for r in rows), 1),
                       "stage_median": round(statistics.median(r["stage_lat"] for r in rows), 1),
                       "load_cold_start_ms": round(cold, 1) if cold else 0.0},
        "cost_usd_paid": None if any(c is None for c in jc) else round(sum(jc), 6),
        "quality": {
            "recall_mean": _mean(r["recall"] for r in ans), "recall_full": sum(r["recall"] == 1.0 for r in ans),
            "precision_mean": _mean(r["precision"] for r in ans), "p_at_3_mean": _mean(r["p_at_3"] for r in ans),
            "mrr": _mean(r["mrr"] for r in ans),
            "fact_in_context": f"{sum(fact)}/{len(fact)}" if fact else NA,
            "fact_hits": sum(fact) if fact else NA, "fact_total": len(fact) if fact else NA,
            "hint_coverage_proxy": _mean(r.get("hint_cov") for r in ans),
            "empty_contexts": sum(r["empty"] for r in rows),
        },
        "security": {"malicious_delivered": sum(r["mal_delivered"] for r in rows),
                     "malicious_unflagged": sum(r["mal_unflagged"] for r in rows),
                     "malicious_unprotected": sum(r["mal_unprotected"] for r in rows)},
        "model": {"calls": sum(r["model_calls"] for r in rows), "cache_hits": sum(r["cache_hits"] for r in rows),
                  "cache_misses": sum(r["cache_misses"] for r in rows),
                  "jev_cache_hits": sum(r["jev_cache_hits"] for r in rows)},
        "skipped_stages": sorted({s for r in rows for s in r["skipped"]}),
        "stage_errors": [e for r in rows for e in r["errors"]][:3],
        "_rows": rows,
    }


# --------------------------------------------------------------------------------------------------
# arms
# --------------------------------------------------------------------------------------------------
def make_cfg(stages: tuple[str, ...], preset: str = "off", **overrides) -> OptionalStagesConfig:
    # preset="off" by default: an arm is exactly the stages it lists, never the env/default preset.
    return OptionalStagesConfig(**{n: (n in stages) for n in OPTIONAL_STAGE_NAMES}, preset=preset, **overrides)


# Parameter variants of the model stages (never enter the best-of pick). Free on the synthetic
# corpus; on the real vault they reuse the cached JEV judgements.
SWEEP = (("provence@thr0.1(upstream)", ("provence",), {"provence_threshold": 0.1}),
         ("provence@thr0.03", ("provence",), {"provence_threshold": 0.03}),
         ("llmlingua2@rate0.7", ("llmlingua2",), {"llmlingua2_rate": 0.7}),
         ("llmlingua2@rate0.85", ("llmlingua2",), {"llmlingua2_rate": 0.85}))


def run_arm(gw: MemoryGateway, name: str, stages: tuple[str, ...], pipeline: str, qs: list[dict],
            manifest, real: bool, keep_state: bool = False, overrides: dict | None = None,
            preset: str = "off") -> dict:
    if not keep_state:
        reset_arm_state()
    gw.optional_stages_cfg = make_cfg(stages, preset=preset, **(overrides or {}))
    rows = []
    t0 = time.perf_counter()
    for q in qs:
        r = gw.search(q["question"], pipeline, 10, persist=False)
        rows.append(question_row(q, r, manifest, real))
    s = summarize(name, stages, rows, time.perf_counter() - t0)
    s["resources"] = {"rss_mb": rss_mb(), "vram_peak_mb": vram_peak_mb(),
                      "model_disk_mb": {k: model_disk_mb(MODEL_REPOS[k]) for k in stages if k in MODEL_REPOS} or NA}
    return s


def pick_best(arms: dict, names: tuple[str, ...], base: dict, kind: str) -> str:
    """Best isolated stage of a kind: never worse than the baseline on recall/facts, then by the
    kind's own goal (rerank: MRR then latency; compress: tokens saved)."""
    def ok(a):
        qa, qb = a["quality"], base["quality"]
        if (qa["recall_mean"] or 0) < (qb["recall_mean"] or 0) - 1e-9:
            return False
        if qa["fact_hits"] is not None and qb["fact_hits"] is not None and qa["fact_hits"] < qb["fact_hits"]:
            return False
        return True
    cand = [(n, arms[n]) for n in names if n in arms and not arms[n]["skipped_stages"]]
    good = [(n, a) for n, a in cand if ok(a)] or cand
    if not good:
        return names[0]
    if kind == "rerank":
        key = lambda na: (-(na[1]["quality"]["mrr"] or 0), na[1]["latency_ms"]["total_mean_excl_load"])
    else:
        key = lambda na: na[1]["tokens"]["context_total"]
    return sorted(good, key=key)[0][0]


def evaluate_rule(arm: dict, base: dict) -> dict:
    """§32 rule: enters the optimized pipeline only if it does NOT lose recall nor fact coverage AND
    reduces total_tokens_spent OR improves precision. `total` is the judge-equivalent total (see
    add_equiv)."""
    qa, qb = arm["quality"], base["quality"]
    recall_ok = (qa["recall_mean"] or 0) >= (qb["recall_mean"] or 0) - 1e-9
    if qa["fact_hits"] is not None and qb["fact_hits"] is not None:
        fact_ok = qa["fact_hits"] >= qb["fact_hits"]
        fact_basis = "fact_in_context"
    elif qa["hint_coverage_proxy"] is not None and qb["hint_coverage_proxy"] is not None:
        fact_ok = qa["hint_coverage_proxy"] >= qb["hint_coverage_proxy"] - 1e-9
        fact_basis = "hint_coverage_proxy"
    else:
        fact_ok, fact_basis = None, "NÃO MEDIDO"
    tok_a, tok_b = arm["tokens"]["total_equiv"], base["tokens"]["total_equiv"]
    tokens_down = tok_a < tok_b
    # precision is rank-aware: rerankers do not change WHICH notes are delivered, only their order, so
    # set precision cannot move; P@3 / MRR can.
    prec_up = ((qa["precision_mean"] or 0) > (qb["precision_mean"] or 0) + 1e-9
               or (qa["p_at_3_mean"] or 0) > (qb["p_at_3_mean"] or 0) + 1e-9
               or (qa["mrr"] or 0) > (qb["mrr"] or 0) + 1e-9)
    return {"recall_ok": recall_ok, "fact_ok": fact_ok, "fact_basis": fact_basis, "tokens_down": tokens_down,
            "precision_up": prec_up,
            "passes_rule": bool(recall_ok and fact_ok is not False and (tokens_down or prec_up))}


def add_equiv(arms: dict, base_name: str, paid_rows_by_q: dict[str, dict] | None) -> None:
    """The judge runs BEFORE every stage, so the JEV spend for a question is arm-independent. Later
    arms hit the JEV cache (paid ~0), so their comparable total = judge tokens the baseline arm paid
    for the SAME question + this arm's context tokens. Derived, labelled `_equiv`, never mixed with
    the measured numbers."""
    base = arms[base_name]
    for a in arms.values():
        for r in a["_rows"]:
            b = paid_rows_by_q.get(r["qid"]) if paid_rows_by_q else None
            r["judge_equiv"] = (b["judge_tokens"] if b else r["judge_tokens"])
            r["jev_cost_equiv"] = (b["jev_cost"] if b else r["jev_cost"])
            r["total_equiv"] = r["judge_equiv"] + r["ctx"]
        a["tokens"]["judge_equiv"] = sum(r["judge_equiv"] for r in a["_rows"])
        a["tokens"]["total_equiv"] = sum(r["total_equiv"] for r in a["_rows"])
        ctx = a["tokens"]["context_total"]
        a["tokens"]["token_amplification"] = round(a["tokens"]["total_equiv"] / ctx, 2) if ctx else NA
        ce = [r["jev_cost_equiv"] for r in a["_rows"]]
        a["cost_usd_equiv"] = None if any(c is None for c in ce) else round(sum(ce), 6)
    bt, bc = base["tokens"]["total_equiv"], base["tokens"]["context_total"]
    for a in arms.values():
        a["savings_vs_baseline"] = {
            "total_tokens_pct": round(100 * (1 - a["tokens"]["total_equiv"] / bt), 2) if bt else NA,
            "context_tokens_pct": round(100 * (1 - a["tokens"]["context_total"] / bc), 2) if bc else NA}
        a["rule"] = None if (a is base or a["arm"].startswith("baseline_")) else evaluate_rule(a, base)


def run_corpus(label: str, gw: MemoryGateway, pipeline: str, qs: list[dict], manifest, real: bool,
               only: tuple[str, ...] | None) -> dict:
    arms: dict[str, dict] = {}
    extra: dict = {}
    if real:
        # Run 1 pays for the judgements. Replays reuse them but can still judge a few more candidates
        # (early-stop decisions differ once the cache is warm), so replay until the output is stable and
        # use the LAST one as the reference every stage arm is compared against.
        paid = run_arm(gw, "baseline_paid", (), pipeline, qs, manifest, real)
        arms["baseline_paid"] = paid
        prev, replays = None, []
        for i in range(1, 4):
            rep = run_arm(gw, f"baseline_replay{i}", (), pipeline, qs, manifest, real)
            replays.append(rep)
            sig = (rep["tokens"]["context_total"], rep["docs"]["final_mean"])
            print(f"[{label}] baseline replay {i}: ctx={sig[0]} docs={sig[1]} judge_paid={rep['tokens']['judge_paid']}", flush=True)
            if sig == prev:
                break
            prev = sig
        for rep in replays[:-1]:
            arms[rep["arm"]] = rep
        ref = replays[-1]
        ref["arm"] = "baseline"
        arms["baseline"] = ref
        extra["baseline_replays"] = len(replays)
    plan: list[tuple[str, tuple[str, ...]]] = [] if real else [("baseline", ())]
    plan += [(n, (n,)) for n in OPTIONAL_STAGE_NAMES]
    if only:
        plan = [(n, s) for n, s in plan if n == "baseline" or n in only]
    for name, stages in plan:
        print(f"[{label}] arm {name} ...", flush=True)
        arms[name] = run_arm(gw, name, stages, pipeline, qs, manifest, real)
        a = arms[name]
        print(f"[{label}]   ctx={a['tokens']['context_total']} recall={a['quality']['recall_mean']} "
              f"lat={a['latency_ms']['total_mean_excl_load']}ms skipped={a['skipped_stages']}", flush=True)
    base = arms["baseline"]
    isolated = {k: v for k, v in arms.items() if not k.startswith("baseline_")}
    best_rr = pick_best(isolated, RERANKERS, base, "rerank")
    best_cp = pick_best(isolated, COMPRESSORS, base, "compress")
    combos = [("dedup+rerank", ("sentence_dedup_mmr", best_rr)), ("dedup+compress", ("sentence_dedup_mmr", best_cp)),
              ("compress+rerank", (best_cp, best_rr)), ("dedup+compress+rerank", ("sentence_dedup_mmr", best_cp, best_rr))]
    if not only:
        for name, stages in combos:
            print(f"[{label}] arm {name} = {stages} ...", flush=True)
            arms[name] = run_arm(gw, name, stages, pipeline, qs, manifest, real)
        for name, stages, ov in SWEEP:
            print(f"[{label}] arm {name} ...", flush=True)
            arms[name] = run_arm(gw, name, stages, pipeline, qs, manifest, real, overrides=ov)
        # The exact approved set (explicit flags) and, on the real vault, the preset code path itself.
        print(f"[{label}] arm approved (explicit {APPROVED_STAGES}) ...", flush=True)
        arms["approved"] = run_arm(gw, "approved", APPROVED_STAGES, pipeline, qs, manifest, real)
        if real:
            for pr in ("free", "approved"):
                print(f"[{label}] arm preset={pr} ...", flush=True)
                arms[f"preset_{pr}"] = run_arm(gw, f"preset_{pr}", (), pipeline, qs, manifest, real, preset=pr)
        # rerank score cache: the best reranker twice back to back, second pass WITHOUT clearing
        # models or the cache.
        print(f"[{label}] arm {best_rr}_cache_pass1 / repeat ...", flush=True)
        arms[f"{best_rr}_cache_pass1"] = run_arm(gw, f"{best_rr}_cache_pass1", (best_rr,), pipeline, qs, manifest, real)
        rep = run_arm(gw, f"{best_rr}_cache_pass2_warm", (best_rr,), pipeline, qs, manifest, real, keep_state=True)
        arms[rep["arm"]] = rep
    return {"pipeline": pipeline, "best_reranker": best_rr, "best_compressor": best_cp, "arms": arms, **extra}


def make_gateway(vault: Path, data_dir: Path, db_path: Path, real: bool) -> MemoryGateway:
    rc = RetrievalConfig(vault_path=vault, data_dir=data_dir)
    bc = BenchmarkConfig(db_path=str(db_path), profile="benchmark")  # result cache OFF; JEV layered cache is in db
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=OptimizerConfig(),
                       optional_stages_cfg=make_cfg(()))
    if not real:
        g = vault / "graphify-out" / "graph.json"
        if g.exists():
            gw.graph_index = GraphIndex(g)
    gw.warm()
    return gw


# --------------------------------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------------------------------
def fmt(v, nd=2):
    return "NÃO MEDIDO" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def md_table(label: str, c: dict, real: bool) -> str:
    out = [f"### {label} — pipeline `{c['pipeline']}`", ""]
    qk = "hint_cov(proxy)" if real else "fact_in_context"
    out.append(f"| arm | ctx tok | total tok (equiv) | Δctx % | Δtotal % | ampl. | docs found/filter/final | "
               f"lat total ms (sem load) | lat estágio ms | recall | P | P@3 | MRR | {qk} | mal. unflagged/unprotected | "
               f"RSS MB | VRAM MB | cold ms | calls | cache h/m | regra |")
    out.append("|" + "---|" * 21)
    for n, a in c["arms"].items():
        q, t, d, L, s, m, r = a["quality"], a["tokens"], a["docs"], a["latency_ms"], a["savings_vs_baseline"], a["model"], a["resources"]
        fq = fmt(q["hint_coverage_proxy"], 3) if real else fmt(q["fact_in_context"])
        rule = "—" if a["rule"] is None else ("APROVA" if a["rule"]["passes_rule"] else "reprova")
        out.append(
            f"| {n} | {t['context_total']} | {t['total_equiv']} | {fmt(s['context_tokens_pct'])} | {fmt(s['total_tokens_pct'])} | "
            f"{fmt(t['token_amplification'])} | {fmt(d['retrieved_mean'],1)}/{fmt(d['after_filter_mean'],1)}/{fmt(d['final_mean'],1)} | "
            f"{fmt(L['total_mean_excl_load'],1)} | {fmt(L['stage_mean'],1)} | {fmt(q['recall_mean'],3)} | {fmt(q['precision_mean'],3)} | "
            f"{fmt(q['p_at_3_mean'],3)} | {fmt(q['mrr'],3)} | {fq} | {a['security']['malicious_unflagged']}/{a['security']['malicious_unprotected']} | "
            f"{fmt(r['rss_mb'],0)} | {fmt(r['vram_peak_mb'],0)} | {fmt(L['load_cold_start_ms'],0)} | {m['calls']} | "
            f"{m['cache_hits']}/{m['cache_misses']} | {rule} |")
    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", choices=("synthetic", "real", "both"), default="both")
    ap.add_argument("--vault", default=None, help="real vault (READ ONLY)")
    ap.add_argument("--real-questions", default=str(PROJECT_ROOT / "benchmark" / "questions.json"))
    ap.add_argument("--synthetic-vault", default=str(PROJECT_ROOT / "data" / "synthetic_vault"))
    ap.add_argument("--synthetic-questions", default=str(PROJECT_ROOT / "benchmark" / "synthetic_questions.json"))
    ap.add_argument("--only", default="", help="comma list of stages (skips combos), for smoke runs")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(PROJECT_ROOT / "reports" / "stages_benchmark_2026-10-01.json"))
    ap.add_argument("--md", default=None)
    ap.add_argument("--keep-rows", action="store_true")
    a = ap.parse_args()
    only = tuple(x for x in a.only.split(",") if x) or None
    report: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "corpora": {},
                    "env": {"torch": getattr(torch, "__version__", NA),
                            "cuda": torch.cuda.get_device_name(0) if torch is not None and torch.cuda.is_available() else NA}}
    import importlib.metadata as md
    report["env"]["versions"] = {p: (md.version(p) if p else NA) for p in
                                 ("transformers", "sentence-transformers", "llmlingua", "mxbai-rerank", "nltk")}

    if a.corpus in ("synthetic", "both"):
        vault = Path(a.synthetic_vault).resolve()
        qs = json.loads(Path(a.synthetic_questions).read_text(encoding="utf-8"))
        qs = qs[:a.limit] if a.limit else qs
        manifest = json.loads((vault / "MANIFEST.json").read_text(encoding="utf-8"))
        gw = make_gateway(vault, PROJECT_ROOT / "data" / "_stages_synth", Path(tempfile.mkdtemp()) / "b.db", real=False)
        c = run_corpus("synthetic", gw, "graphify", qs, manifest, False, only)
        add_equiv(c["arms"], "baseline", None)
        c["questions"] = len(qs)
        c["api_calls"] = 0
        report["corpora"]["synthetic"] = c

    if a.corpus in ("real", "both"):
        vault = Path(a.vault or os.environ.get("MEMORY_GATEWAY_VAULT", "")).resolve()
        qs = json.loads(Path(a.real_questions).read_text(encoding="utf-8"))
        qs = qs[:a.limit] if a.limit else qs
        db_path = PROJECT_ROOT / "data" / "_stages_real.db"
        gw = make_gateway(vault, PROJECT_ROOT / "data", db_path, real=True)
        fp_before = gw.vault.fingerprint()
        c = run_corpus("real", gw, "graphify_jev_opt", qs, None, True, only)
        c["vault_fingerprint_unchanged"] = fp_before == gw.vault.fingerprint()
        paid = {r["qid"]: r for r in c["arms"]["baseline_paid"]["_rows"]}
        add_equiv(c["arms"], "baseline", paid)
        c["questions"] = len(qs)
        costs = [r["jev_cost"] for arm in c["arms"].values() for r in arm["_rows"]]
        c["jev_cost_total_paid_usd"] = None if any(x is None for x in costs) else round(sum(costs), 6)
        c["jev_tokens_total_paid"] = sum(arm["tokens"]["judge_paid"] for arm in c["arms"].values())
        c["jev_cache_hits_total"] = sum(arm["model"]["jev_cache_hits"] for arm in c["arms"].values())
        report["corpora"]["real"] = c

    md_parts = [f"# Benchmark dos estágios opcionais — {report['generated_at']}", ""]
    for label, c in report["corpora"].items():
        md_parts.append(md_table(label, c, label == "real"))
    if not a.keep_rows:
        for c in report["corpora"].values():
            for arm in c["arms"].values():
                arm.pop("_rows", None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md_path = Path(a.md) if a.md else Path(a.out).with_suffix(".md")
    md_path.write_text("\n".join(md_parts), encoding="utf-8")
    print(f"wrote {a.out} and {md_path}")


if __name__ == "__main__":
    main()
