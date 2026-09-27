"""Text report of a benchmark session (§88, §111, §121). Observed numbers only — no verdicts (§91)."""
from __future__ import annotations

from app.benchmark.statistics import describe
from app.services.pricing import break_even

ROWS = [("Latency ms (median)", "total_latency_ms"), ("Retrieval ms", "retrieval_latency_ms"),
        ("Documents found", "documents_found"), ("Docs to model", "documents_sent_to_model"),
        ("Candidate tokens", "candidate_tokens_before_filter"), ("Context tokens", "context_tokens"),
        ("JEV tokens", "jev_tokens"), ("JEV latency ms", "jev_latency_ms"), ("JEV cost USD", "jev_cost"),
        ("Model input tokens", "model_input_tokens"), ("Model output tokens", "model_output_tokens"),
        ("Agent total tokens", "agent_tokens"), ("Generation ms", "generation_latency_ms"),
        ("Total cost USD", "total_cost")]
PIPES = ("baseline", "graphify", "graphify_jev")


def _fmt(v):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if abs(v) < 1 else f"{v:.1f}"
    return str(v)


def render_session(db, session_id: str) -> str:
    runs = [r for r in db.list_runs(100000, session_id) if not r.get("warmup")]
    if not runs:
        return f"sessão {session_id}: sem runs"
    lines = [f"SESSION {session_id}  ({len(runs)} runs, warm-up excluído, cache_enabled=false)"]
    consumers = sorted({(r.get("agent") or "retrieval-only", r.get("model") or "-") for r in runs})
    for agent, model in consumers:
        sub = [r for r in runs if (r.get("agent") or "retrieval-only") == agent and (r.get("model") or "-") == model]
        lines.append(f"\n{agent} / {model}")
        lines.append(f"{'':<22}" + "".join(f"{p.upper():>16}" for p in PIPES))
        med = {}
        for p in PIPES:
            ms = [r["metrics"] for r in sub if r["pipeline"] == p]
            med[p] = {k: describe(m.get(k) for m in ms)["median"] for _, k in ROWS}
            med[p]["_n"] = len(ms)
        for label, k in ROWS:
            vals = [med[p][k] for p in PIPES]
            if all(v is None for v in vals):
                continue
            lines.append(f"{label:<22}" + "".join(f"{_fmt(v):>16}" for v in vals))
        jev = [r["metrics"].get("jev") or {} for r in sub if r["pipeline"] == "graphify_jev"]
        if jev:
            tot = lambda k: sum((j.get(k) or 0) for j in jev)  # noqa: E731
            rel = [j.get("average_relevance") for j in jev if j.get("average_relevance") is not None]
            lines.append(f"\nJEV ({jev[0].get('jev_model_resolved') or jev[0].get('jev_model')}, sdk "
                         f"{jev[0].get('jev_sdk_version')}, mode={jev[0].get('jev_mode')}, "
                         f"threshold={jev[0].get('relevance_threshold')}, REVIEW→{jev[0].get('review_action')})")
            lines.append(f"  candidates={tot('candidates_received')} kept={tot('candidates_kept')} "
                         f"review={tot('candidates_review')} dropped={tot('candidates_dropped')} "
                         f"quarantined={tot('candidates_quarantined')} unjudged={tot('candidates_unjudged')}")
            lines.append(f"  requests={tot('request_count')} input_tokens={tot('input_tokens')} "
                         f"avg_relevance={round(sum(rel) / len(rel), 3) if rel else 'n/a'} errors={sum(len(j.get('errors') or []) for j in jev)}")
        be = break_even({k: med["graphify"].get(k) for _, k in ROWS} | {"model_cost": med["graphify"].get("total_cost")},
                        {k: med["graphify_jev"].get(k) for _, k in ROWS} | {"model_cost": None,
                                                                             "jev_input_tokens": med["graphify_jev"].get("jev_tokens")})
        lines.append("  Graphify → Graphify+JEV (medianas): "
                     f"context_reduction={_fmt(be['context_reduction_percent'])}% "
                     f"tokens_saved={_fmt(be['context_tokens_saved'])} "
                     f"net_latency_change={_fmt(be['net_latency_change_ms'])}ms "
                     f"net_cost_change={_fmt(be['net_cost_change'])} USD")
    fn = db.false_negative_rate()
    lines.append(f"\nFalse negatives (marcados): {fn['false_negatives']} / {fn['dropped_total']} descartados "
                 f"→ rate={fn['false_negative_rate']}")
    lines.append("Observação: números observados; nenhuma conclusão de qualidade sem avaliação humana.")
    return "\n".join(lines)
