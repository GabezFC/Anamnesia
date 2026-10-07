"""R5: routing metrics. PURE functions over per-task records: no I/O, no model calls, no network.

A *record* is a dict describing ONE task under ONE strategy (see routing_bench.make_record):
  task_id, kind, difficulty, strategy, solved(bool), cost(float|None), cost_origin, tokens(int|None),
  final_cost (cost of the last attempt only), retry_cost (cost of earlier attempts),
  router_cost, verify_cost, router_tokens, verify_tokens, initial_tier, final_tier,
  escalation_count, retry_count(int|None), t_star(int|None), oracle_cost(float|None),
  penalty_cost(float|None), simulated(bool).

Every figure returned to a user is a *labelled value* {"value": x|None, "origin": "measured|estimated|unavailable"}.
A missing price (cost None) NEVER becomes 0: any aggregate that needs it is null/unavailable.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence

ORIGINS = ("measured", "estimated", "unavailable")
ORIGIN_PT = {"measured": "medido", "estimated": "estimado", "unavailable": "indisponível"}
DIFFICULTIES = ("easy", "medium", "hard")
DYNAMIC = "DYNAMIC_ROUTER"
BASELINE = "STATIC_DEFAULT"


def lv(value, origin: str = "measured") -> dict:
    """Labelled value; None always carries origin 'unavailable'."""
    if value is None:
        return {"value": None, "origin": "unavailable"}
    return {"value": value, "origin": origin if origin in ORIGINS else "estimated"}


def combine_origin(origins: Iterable[str | None]) -> str:
    os_ = [o or "unavailable" for o in origins]
    if not os_ or "unavailable" in os_:
        return "unavailable"
    return "estimated" if "estimated" in os_ else "measured"


def _sum(values: Sequence) -> float | None:
    """Sum, or None when ANY value is None (unavailable price/tokens is never treated as 0)."""
    if not values or any(v is None for v in values):
        return None
    return float(sum(values))


def _rate(num: int, den: int):
    return None if den <= 0 else num / den


def _r(x, nd=6):
    return None if x is None else round(x, nd)


# ------------------------------------------------------------------ cost / tokens
def total_cost(records: Sequence[dict]) -> dict:
    v = _sum([r.get("cost") for r in records])
    return lv(_r(v), combine_origin(r.get("cost_origin") if r.get("cost") is not None else None for r in records))


def total_tokens(records: Sequence[dict]) -> dict:
    v = _sum([r.get("tokens") for r in records])
    return lv(None if v is None else int(v), "measured" if v is not None and not any(
        r.get("tokens_origin") == "estimated" for r in records) else "estimated")


def solved_count(records: Sequence[dict]) -> int:
    return sum(1 for r in records if r.get("solved") is True)


def success_rate(records: Sequence[dict]) -> dict:
    return lv(_r(_rate(solved_count(records), len(records))), "measured")


def cost_per_solved_task(records: Sequence[dict]) -> dict:
    """total operational cost / solved tasks. null if no task solved or any cost unavailable."""
    n = solved_count(records)
    tc = total_cost(records)
    if n == 0 or tc["value"] is None:
        return lv(None)
    return lv(_r(tc["value"] / n), tc["origin"])


def tokens_per_solved_task(records: Sequence[dict]) -> dict:
    n = solved_count(records)
    tt = total_tokens(records)
    if n == 0 or tt["value"] is None:
        return lv(None)
    return lv(_r(tt["value"] / n), tt["origin"])


# ------------------------------------------------------------------ escalation / retry
def escalation_rate(records: Sequence[dict]) -> dict:
    """Share of tasks that needed >= 1 escalation (switch to a higher-tier model)."""
    if not records:
        return lv(None)
    return lv(_r(sum(1 for r in records if (r.get("escalation_count") or 0) > 0) / len(records)), "measured")


def retry_rate(records: Sequence[dict]) -> dict:
    """Share of tasks with >= 1 retry on the SAME model. Unavailable when the harness never recorded retries."""
    known = [r for r in records if r.get("retry_count") is not None]
    if not known:
        return lv(None)
    return lv(_r(sum(1 for r in known if r["retry_count"] > 0) / len(known)), "measured")


# ------------------------------------------------------------------ oracle t*, over/under-routing, regret
def oracle_for_task(cells: dict) -> dict | None:
    """cells: {model_id: {"tier": int, "solved": bool, "cost": float|None}} for ONE task.

    t* = lowest tier among models that solved it. Oracle model = the cheapest solving model
    (known costs first; ties/unknown costs fall back to tier then id). None when nobody solved it.
    """
    solving = [(mid, c) for mid, c in cells.items() if c.get("solved")]
    if not solving:
        return None
    t_star = min(c["tier"] for _, c in solving)
    best = min(solving, key=lambda mc: (mc[1].get("cost") is None, mc[1].get("cost") or 0.0, mc[1]["tier"], mc[0]))
    return {"t_star": t_star, "model": best[0], "cost": best[1].get("cost"), "tier": best[1]["tier"]}


def routing_classification(records: Sequence[dict]) -> dict:
    """over: chose tier > t* and solved (paid too much). under: chose tier < t* (failed or needed escalation).

    Uses the INITIAL tier picked by the policy. Tasks without t* (nobody solves / oracle not run) are
    excluded and counted in `no_tstar`.
    """
    over = under = exact = no_t = 0
    for r in records:
        t, ts = r.get("initial_tier"), r.get("t_star")
        if ts is None or t is None:
            no_t += 1
        elif t > ts and r.get("solved"):
            over += 1
        elif t < ts:
            under += 1
        else:
            exact += 1
    judged = over + under + exact
    return {"over_routed": over, "under_routed": under, "exact": exact, "no_tstar": no_t, "judged": judged,
            "over_rate": lv(_r(_rate(over, judged))), "under_rate": lv(_r(_rate(under, judged)))}


def task_regret(record: dict) -> float | None:
    """cost(policy) - cost(oracle); a failed task also pays `penalty_cost` (a redo on the strongest model)."""
    c, o = record.get("cost"), record.get("oracle_cost")
    if c is None or o is None:
        return None
    if record.get("solved"):
        return c - o
    p = record.get("penalty_cost")
    return None if p is None else c + p - o


def regret(records: Sequence[dict]) -> dict:
    """Total / mean regret over tasks that have an oracle. Null if any needed price is unavailable."""
    judged = [r for r in records if r.get("t_star") is not None]
    vals = [task_regret(r) for r in judged]
    tot = _sum(vals)
    origin = combine_origin(r.get("cost_origin") for r in judged) if tot is not None else "unavailable"
    by_d = {}
    for d in DIFFICULTIES:
        sub = [task_regret(r) for r in judged if r.get("difficulty") == d]
        s = _sum(sub)
        by_d[d] = lv(_r(None if s is None else s / len(sub)), origin)
    return {"total": lv(_r(tot), origin), "mean": lv(_r(None if tot is None else tot / len(judged)), origin),
            "n": len(judged), "mean_by_difficulty": by_d}


# ------------------------------------------------------------------ break-even
def break_even(dynamic: Sequence[dict], baseline: Sequence[dict]) -> dict:
    """Does routing pay for itself against `baseline` on the SAME tasks?

      model_savings = baseline_total - dynamic_final_attempt_cost        (gross gain from cheaper models)
      overheads     = router + verification + retry/escalation cost       (extra spent by the pipeline)
      net_savings   = model_savings - overheads  (== baseline_total - dynamic_total)
      pays_for_itself = model_savings >= overheads
    All values null when any underlying price is unavailable (then pays_for_itself is None = 'sem dados').
    """
    ids = {r["task_id"] for r in dynamic} & {r["task_id"] for r in baseline}
    d = sorted((r for r in dynamic if r["task_id"] in ids), key=lambda r: r["task_id"])
    b = sorted((r for r in baseline if r["task_id"] in ids), key=lambda r: r["task_id"])
    empty = {"n_tasks": len(ids), "baseline_total": lv(None), "model_savings": lv(None), "routing_overhead": lv(None),
             "verification_overhead": lv(None), "retry_overhead": lv(None), "net_savings": lv(None),
             "net_savings_percent": lv(None), "quality_delta": lv(None), "pays_for_itself": None}
    if not ids:
        return empty
    base_total = _sum([r.get("cost") for r in b])
    dyn_final = _sum([r.get("final_cost") for r in d])
    router = _sum([r.get("router_cost") for r in d])
    verify = _sum([r.get("verify_cost") for r in d])
    retry = _sum([r.get("retry_cost") for r in d])
    origin = combine_origin([r.get("cost_origin") for r in d + b])
    qd = _r(solved_count(d) / len(d) - solved_count(b) / len(b))
    out = dict(empty, quality_delta=lv(qd, "measured"))
    if None in (base_total, dyn_final, router, verify, retry):
        return out
    savings = base_total - dyn_final
    overheads = router + verify + retry
    net = savings - overheads
    out.update(baseline_total=lv(_r(base_total), origin), model_savings=lv(_r(savings), origin),
               routing_overhead=lv(_r(router), origin), verification_overhead=lv(_r(verify), origin),
               retry_overhead=lv(_r(retry), origin), net_savings=lv(_r(net), origin),
               net_savings_percent=lv(_r(None if base_total == 0 else net / base_total * 100, 4), origin),
               pays_for_itself=bool(savings >= overheads - 1e-12))
    return out


def verdict(be: dict, simulated_only: bool = False) -> dict:
    """'SIM' / 'NÃO' / 'sem dados'. SIM requires cost break-even AND no quality regression."""
    if simulated_only:
        return {"value": "sem dados", "reason": "somente dados simulados (stub): não é evidência"}
    pays = be.get("pays_for_itself")
    if pays is None:
        return {"value": "sem dados", "reason": "preço indisponível ou nenhuma tarefa comparável"}
    q = (be.get("quality_delta") or {}).get("value")
    if pays and (q is None or q >= 0):
        return {"value": "SIM", "reason": "economia dos modelos >= overheads do router/verificação/escalonamento"}
    if pays:
        return {"value": "NÃO", "reason": "economiza, mas a taxa de resolução caiu"}
    return {"value": "NÃO", "reason": "overheads maiores que a economia de modelo"}


# ------------------------------------------------------------------ breakdowns
def by_difficulty(records: Sequence[dict]) -> dict:
    out = {}
    for d in DIFFICULTIES:
        sub = [r for r in records if r.get("difficulty") == d]
        out[d] = {"n": len(sub), "solved": solved_count(sub), "success_rate": success_rate(sub) if sub else lv(None),
                  "cost_per_solved_task": cost_per_solved_task(sub), "escalation_rate": escalation_rate(sub)}
    return out


def tier_matrix(records: Sequence[dict]) -> dict:
    """difficulty x initial tier -> number of tasks (counts, measured)."""
    m: dict = {d: defaultdict(int) for d in DIFFICULTIES}
    for r in records:
        if r.get("difficulty") in m and r.get("initial_tier") is not None:
            m[r["difficulty"]][str(r["initial_tier"])] += 1
    return {d: dict(sorted(v.items())) for d, v in m.items()}


def group_compare(dynamic: Sequence[dict], baseline: Sequence[dict], key: str) -> dict:
    """Per group (difficulty or kind): break-even of dynamic vs baseline -> where routing helps / hurts."""
    groups = sorted({r.get(key) for r in dynamic if r.get(key)})
    return {g: break_even([r for r in dynamic if r.get(key) == g], [r for r in baseline if r.get(key) == g])
            for g in groups}


def summarize_strategy(records: Sequence[dict]) -> dict:
    return {"n": len(records), "solved": solved_count(records), "success_rate": success_rate(records),
            "total_cost": total_cost(records), "total_tokens": total_tokens(records),
            "cost_per_solved_task": cost_per_solved_task(records), "tokens_per_solved_task": tokens_per_solved_task(records),
            "escalation_rate": escalation_rate(records), "retry_rate": retry_rate(records),
            "routing": routing_classification(records), "regret": regret(records),
            "by_difficulty": by_difficulty(records)}


def build_summary(records: Sequence[dict]) -> dict:
    """Everything the report and the Custos tab need. Simulated (stub) records never produce figures."""
    sim = [r for r in records if r.get("simulated")]
    real = [r for r in records if not r.get("simulated")]
    out = {"has_data": bool(real), "simulated_records": len(sim), "simulated_only": bool(sim) and not real,
           "n_records": len(real), "strategies": {}, "break_even": None, "verdict": None,
           "difficulty_tier_matrix": None, "escalation_rate": lv(None), "by_difficulty_compare": {}, "by_kind_compare": {}}
    if not real:
        out["verdict"] = verdict({}, simulated_only=bool(sim)) if sim else {"value": "sem dados", "reason": "nenhuma execução registrada"}
        return out
    by_s: dict = defaultdict(list)
    for r in real:
        by_s[r["strategy"]].append(r)
    out["strategies"] = {s: summarize_strategy(v) for s, v in sorted(by_s.items())}
    dyn = by_s.get(DYNAMIC) or next((v for k, v in sorted(by_s.items()) if k.startswith(DYNAMIC)), [])
    base = by_s.get(BASELINE, [])
    if dyn:
        out["difficulty_tier_matrix"] = tier_matrix(dyn)
        out["escalation_rate"] = escalation_rate(dyn)
    if dyn and base:
        out["break_even"] = break_even(dyn, base)
        out["by_difficulty_compare"] = group_compare(dyn, base, "difficulty")
        out["by_kind_compare"] = group_compare(dyn, base, "kind")
    out["verdict"] = verdict(out["break_even"] or {}) if out["break_even"] else {
        "value": "sem dados", "reason": "falta DYNAMIC_ROUTER ou STATIC_DEFAULT para comparar"}
    return out
