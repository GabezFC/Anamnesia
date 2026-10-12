"""ANA-037 / ANA-038: benchmark-only experimental arms (never registered in PIPELINES; the frozen
`graphify_jev` and the production pipelines are untouched) and paired decomposition helpers.

Arms (same signature as app.retrieval.pipelines.PIPELINE_FUNCS):
  baseline_jev          lexical candidates -> prefilter -> JEV           (isolates the JEV effect on lexical)
  graphify_cli          graphify CLI traversal, no hybrid BM25           (== GRAPHIFY_HYBRID=false)
  graph_only            only candidates found purely by graph structure  (isolates the graph effect)
  baseline_graph_no_jev baseline + graph neighbours, no judge            (graph effect without JEV cost)
  no_gateway            ANA-038: whole vault truncated to a budget, or no context at all
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app.benchmark.statistics import mcnemar_exact, paired_diff_ci
from app.gateway.token_budget import estimate_tokens
from app.retrieval.pipelines import (_apply_scope, _graphify_candidates, full_note_text,
                                     run_baseline, run_graphify)
from app.services.dedup import deduplicate, preprocess
from app.services.prefilter import prefilter

BM25_BAND_MIN = 0.55  # hybrid_search: BM25 hits score >= 0.55, graph-only neighbours <= 0.5


def run_baseline_jev(gw, query: str, max_results: int, jev=None):
    rc = gw.retrieval_cfg
    raw = gw.baseline.search(query, limit=rc.max_candidates)
    raw, _ = _apply_scope(gw, raw)
    uniq, _ = deduplicate(preprocess(raw, rc.snippet_max_tokens), rc.dedup_max_per_note)
    judged_in, withheld, pf = prefilter(query, uniq, rc.prefilter_top_k, rc.prefilter_lexical_weight)
    jev = jev or gw.jev
    survivors, jm = jev.evaluate(query, judged_in)
    survivors = sorted(survivors, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]
    full = {c.candidate_id: full_note_text(gw, c) for c in survivors}
    jd = jm.to_dict()
    return survivors, full, {**pf, "arm": "baseline_jev", "documents_sent_to_jev": len(judged_in),
                             "jev_input_tokens": jd["input_tokens"], "jev_output_tokens": jd["output_tokens"],
                             "jev": jd, "_all_candidates": judged_in + withheld}


def run_graphify_cli(gw, query: str, max_results: int):
    rc = gw.retrieval_cfg
    raw, ginfo = gw.graphify.search(query, limit=rc.max_candidates)
    raw, _ = _apply_scope(gw, raw)
    uniq, _ = deduplicate(preprocess(raw, rc.snippet_max_tokens), rc.dedup_max_per_note)
    return uniq[:max_results], {}, {**ginfo, "arm": "graphify_cli", "graphify_mode": "cli"}


def run_graph_only(gw, query: str, max_results: int):
    uniq, metrics = _graphify_candidates(gw, query, allow_ppr=False)
    only = [c for c in uniq if c.score < BM25_BAND_MIN]
    metrics["dedup_latency_ms"] = metrics.get("dedup_latency_ms", 0)
    return only[:max_results], {}, {**metrics, "arm": "graph_only", "graph_only_kept": len(only),
                                    "graph_only_dropped_bm25": len(uniq) - len(only)}


def run_baseline_graph_no_jev(gw, query: str, max_results: int):
    c, f, m = run_graphify(gw, query, max_results)
    return c, f, {**m, "arm": "baseline_graph_no_jev"}


def no_gateway_context(gw, budget_tokens: int, mode: str = "vault_truncated") -> dict[str, Any]:
    """ANA-038 NO_GATEWAY control. `mode='none'` -> empty context; otherwise the vault concatenated in
    path order, cut at `budget_tokens` (the same budget the Gateway arms get). Read-only."""
    if mode == "none":
        return {"context": "", "tokens": 0, "arm": "NO_GATEWAY", "mode": mode, "files": 0}
    parts: list[str] = []
    used = files = 0
    for rel in sorted(gw.vault.list_searchable()):
        try:
            text = gw.vault.read(rel)
        except Exception:  # noqa: BLE001
            continue
        t = estimate_tokens(text)
        if used + t > budget_tokens:
            remaining = budget_tokens - used
            if remaining > 0:
                parts.append(text[: remaining * 4])
                used = budget_tokens
                files += 1
            break
        parts.append(text)
        used += t
        files += 1
    return {"context": "\n\n".join(parts), "tokens": used, "arm": "NO_GATEWAY", "mode": mode, "files": files}


EXPERIMENTAL_ARMS: dict[str, Callable] = {
    "baseline_jev": run_baseline_jev,
    "graphify_cli": run_graphify_cli,
    "graph_only": run_graph_only,
    "baseline_graph_no_jev": run_baseline_graph_no_jev,
}


def run_arm(name: str, gw, query: str, max_results: int = 10, **kw):
    """Run any production-or-experimental arm (benchmark-only entry point)."""
    if name in EXPERIMENTAL_ARMS:
        return EXPERIMENTAL_ARMS[name](gw, query, max_results, **kw)
    from app.retrieval.pipelines import PIPELINE_FUNCS
    return PIPELINE_FUNCS[name](gw, query, max_results, **kw)


def paired_effect(a: list[dict], b: list[dict], ok_key: str = "ok", metric_key: str | None = None) -> dict:
    """Per-question paired comparison of arm A vs arm B. Rows are {'qid', ok_key[, metric_key]}.
    Returns McNemar on the binary outcome and a bootstrap CI on the paired metric difference."""
    bm = {r["qid"]: r for r in b}
    pairs = [(r, bm[r["qid"]]) for r in a if r["qid"] in bm]
    out: dict[str, Any] = {"n_pairs": len(pairs)}
    if not pairs:
        return out
    out["mcnemar"] = mcnemar_exact([bool(x[ok_key]) for x, _ in pairs], [bool(y[ok_key]) for _, y in pairs])
    if metric_key:
        out["paired_diff"] = paired_diff_ci([x.get(metric_key) for x, _ in pairs],
                                            [y.get(metric_key) for _, y in pairs])
    return out


def decompose(rows_by_arm: dict[str, list[dict]], **kw) -> dict[str, Any]:
    """Effect decomposition: graph (graphify vs baseline), JEV (graphify_jev vs graphify; baseline_jev vs
    baseline), prefilter (graphify_jev vs baseline_graph_no_jev is NOT it -- prefilter needs a top_k=0 run,
    supplied as 'graphify_jev_no_prefilter'), graph-only structure (graph_only vs baseline)."""
    plan = {
        "efeito_grafo": ("graphify", "baseline"),
        "efeito_jev_sobre_grafo": ("graphify_jev", "graphify"),
        "efeito_jev_sobre_lexical": ("baseline_jev", "baseline"),
        "efeito_prefilter": ("graphify_jev", "graphify_jev_no_prefilter"),
        "estrutura_pura": ("graph_only", "baseline"),
        "graphify_cli_vs_hibrido": ("graphify", "graphify_cli"),
    }
    res: dict[str, Any] = {}
    for name, (a, b) in plan.items():
        if a in rows_by_arm and b in rows_by_arm:
            res[name] = {"a": a, "b": b, **paired_effect(rows_by_arm[a], rows_by_arm[b], **kw)}
        else:
            res[name] = {"a": a, "b": b, "skipped": "braço ausente"}
    return res


def vs_no_gateway(gateway_rows: list[dict], no_gw_rows: list[dict]) -> dict[str, Any]:
    """ANA-038: Δtokens and Δquality against NO_GATEWAY, both with CI. Rows: {'qid','ok','tokens'}."""
    return paired_effect(gateway_rows, no_gw_rows, ok_key="ok", metric_key="tokens") | {
        "reference": "NO_GATEWAY", "generated_at": time.strftime("%Y-%m-%d")}
