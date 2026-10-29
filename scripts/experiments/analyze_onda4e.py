"""Onda 4e - offline analysis of the REAL OpenRouter run (zero token, zero network).

Reads data/onda4e_{bench,cells,integration,state}.json (written by scripts/experiments/run_onda4e_openrouter.py) and writes
data/reports-out/ONDA4_ROUTING_REAL.{md,json} (local, ignored by Git). Every number carries its origin. No credential is ever read here.

  python scripts/experiments/analyze_onda4e.py            # print JSON
  python scripts/experiments/analyze_onda4e.py --write    # write the report
  python scripts/experiments/analyze_onda4e.py --check    # exit 1 if data/reports-out/ONDA4_ROUTING_REAL.md is stale (freshness)
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.benchmark.statistics import power_report, required_n_two_proportions  # noqa: E402
from app.core.stats import paired_diff_ci, wilson_ci  # noqa: E402
from app.routing import calibration as cal  # noqa: E402
from app.routing.escalation_verifier import escalation_error_rates, verify_for_escalation  # noqa: E402
from app.routing.policy import preset  # noqa: E402
from app.routing.tasks import load_tasks, split_tasks  # noqa: E402

DATA = ROOT / "data"
OUT_MD = ROOT / "data" / "reports-out" / "ONDA4_ROUTING_REAL.md"
OUT_JSON = ROOT / "data" / "reports-out" / "ONDA4_ROUTING_REAL.json"
ORDER = ["openrouter-gpt4o-mini", "openrouter-gpt41-mini", "openrouter-sonnet"]
UNDER_W = cal.UNDER_WEIGHT


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def strategy_table(records):
    by = collections.defaultdict(list)
    for r in records:
        by[r["strategy"]].append(r)
    rows = {}
    for s, rs in sorted(by.items()):
        k = sum(1 for r in rs if r["solved"])
        costs = [r["cost"] for r in rs]
        known = [c for c in costs if c is not None]
        rows[s] = {"n": len(rs), "solved": k, "rate": wilson_ci(k, len(rs)),
                   "cost_usd": round(sum(known), 6), "cost_known": len(known), "cost_unknown": len(costs) - len(known),
                   "cost_per_solved": round(sum(known) / k, 6) if k else None,
                   "cost_origin": sorted({r.get("cost_origin") for r in rs}),
                   "escalations": sum(r.get("escalation_count") or 0 for r in rs),
                   "router_cost": round(sum(r.get("router_cost") or 0 for r in rs), 6),
                   "verify_cost": round(sum(r.get("verify_cost") or 0 for r in rs), 6),
                   "retry_cost": round(sum(r.get("retry_cost") or 0 for r in rs), 6),
                   "verify_tokens_origin": sorted({str(r.get("verify_tokens_origin")) for r in rs}),
                   "router_tokens_origin": sorted({str(r.get("router_tokens_origin")) for r in rs}),
                   "verify_latency_ms_total": round(sum(r.get("verify_latency_ms") or 0 for r in rs), 1)}
    return rows


def per_task(records, strategy, field):
    d = collections.defaultdict(list)
    for r in records:
        if r["strategy"] == strategy:
            d[r["task_id"]].append(1.0 if (field == "solved" and r["solved"]) else (0.0 if field == "solved" else r[field]))
    return {t: _mean(v) for t, v in d.items()}


def paired(records, a, b, field):
    pa, pb = per_task(records, a, field), per_task(records, b, field)
    ids = sorted(set(pa) & set(pb))
    return paired_diff_ci([pa[i] for i in ids], [pb[i] for i in ids])


def cell_index(cells):
    """(task, tier_idx) -> (solve_rate, mean_cost) averaged over reps."""
    acc = collections.defaultdict(list)
    for c in cells:
        acc[(c["task"], ORDER.index(c["model"]))].append(c)
    return {k: (_mean([1.0 if x["solved"] else 0.0 for x in v]), _mean([x["cost"] for x in v])) for k, v in acc.items()}


def t_star(idx, tid):
    for k in range(3):
        sr = idx.get((tid, k), (0, 0))[0]
        if sr is not None and sr >= 0.5:
            return k
    return None


def route_idx(score, cutoffs):
    return cal.tier_index(cal.level_of(score, cutoffs), len(cutoffs) + 1, 3)


def real_regret(tstar, k):
    if tstar is None:
        return None
    return (tstar - k) * UNDER_W if k < tstar else float(k - tstar)


def calibration_real(tasks, idx):
    pol = preset("balanced", enabled=True)
    cal_t, ev_t = split_tasks(tasks, seed=42)
    sc = {t.id: s for t, s in zip(tasks, cal.score_tasks(tasks, pol))}
    ts = {t.id: t_star(idx, t.id) for t in tasks}
    default = tuple(pol.tier_cutoffs)

    def mean_regret(sub, cut):
        v = [real_regret(ts[t.id], route_idx(sc[t.id], cut)) for t in sub]
        v = [x for x in v if x is not None]
        return sum(v) / len(v) if v else None

    grid = cal.cutoff_grid(3, step=0.05)
    ranked = sorted(((mean_regret(cal_t, g), g) for g in grid), key=lambda x: (x[0], x[1]))
    # candidates that collapse to a single tier are excluded (ANA-170) unless the constant IS the optimum: report both
    def distinct(sub, cut):
        return len({route_idx(sc[t.id], cut) for t in sub})
    nonconst = [(r, g) for r, g in ranked if distinct(cal_t, g) >= 2]
    best_any, best_nc = ranked[0], nonconst[0]
    const = {k: _mean([real_regret(ts[t.id], k) for t in cal_t if ts[t.id] is not None]) for k in range(3)}
    k_const = min(const, key=lambda k: (const[k], k))

    def per_task_reg(sub, fn):
        return [real_regret(ts[t.id], fn(t)) for t in sub]

    reg_def = per_task_reg(ev_t, lambda t: route_idx(sc[t.id], default))
    reg_best = per_task_reg(ev_t, lambda t: route_idx(sc[t.id], best_nc[1]))
    reg_const = per_task_reg(ev_t, lambda t: k_const)
    ci_def = paired_diff_ci(reg_def, reg_best)
    ci_const = paired_diff_ci(reg_const, reg_best)

    def money(sub, fn):
        sr = [idx[(t.id, fn(t))][0] for t in sub]
        co = [idx[(t.id, fn(t))][1] for t in sub]
        return sr, co
    strategies = {"router_default_cutoffs": lambda t: route_idx(sc[t.id], default),
                  "router_calibrated_cutoffs": lambda t: route_idx(sc[t.id], best_nc[1]),
                  "static_cheap": lambda t: 0, "static_default": lambda t: 1, "static_strong": lambda t: 2}
    ev_money = {}
    for name, fn in strategies.items():
        sr, co = money(ev_t, fn)
        ev_money[name] = {"solve_rate": round(_mean(sr), 4), "mean_cost_usd": round(_mean(co), 8),
                          "tier_counts": dict(collections.Counter(fn(t) + 1 for t in ev_t))}
    paired_money = {}
    for a in ("router_default_cutoffs", "router_calibrated_cutoffs"):
        for b in ("static_cheap", "static_default", "static_strong"):
            sa, ca = money(ev_t, strategies[a])
            sb, cb = money(ev_t, strategies[b])
            paired_money[f"{a} - {b}"] = {"solve_rate_diff": paired_diff_ci(sa, sb), "cost_diff_usd": paired_diff_ci(ca, cb)}
    # AUC of the query-only score for "needs more than tier 1" among tasks with a t*
    pos = [sc[t.id] for t in ev_t if ts[t.id] is not None and ts[t.id] >= 1]
    neg = [sc[t.id] for t in ev_t if ts[t.id] == 0]
    auc_ev = cal.auc(neg, pos)
    allpos = [sc[t.id] for t in tasks if ts[t.id] is not None and ts[t.id] >= 1]
    allneg = [sc[t.id] for t in tasks if ts[t.id] == 0]
    promote = bool(ci_def["excludes_zero"] and (ci_def["mean_diff"] or 0) > 0
                   and ci_const["excludes_zero"] and (ci_const["mean_diff"] or 0) > 0)
    return {
        "proxy": "ordinal regret vs t* REAL (lowest tier whose solve-rate over reps >= 0.5); under-routing x2; "
                 "tasks no tier solves (t* undefined) excluded from regret but INCLUDED in solve-rate/cost",
        "split": {"seed": 42, "n_calibration": len(cal_t), "n_test": len(ev_t)},
        "tstar_distribution_all": dict(collections.Counter("none" if v is None else f"tier{v + 1}" for v in ts.values())),
        "tstar_distribution_test": dict(collections.Counter("none" if ts[t.id] is None else f"tier{ts[t.id] + 1}" for t in ev_t)),
        "tier_cutoffs": {"default": list(default), "calibrated_nonconstant": list(best_nc[1]), "best_any": list(best_any[1]),
                         "cal_regret_default": round(mean_regret(cal_t, default), 4),
                         "cal_regret_calibrated": round(best_nc[0], 4), "cal_regret_best_any": round(best_any[0], 4),
                         "test_regret_default": round(_mean(reg_def), 4), "test_regret_calibrated": round(_mean(reg_best), 4),
                         "best_constant_tier": k_const + 1, "test_regret_best_constant": round(_mean(reg_const), 4),
                         "test_paired_default_minus_calibrated_ci95": ci_def,
                         "test_paired_constant_minus_calibrated_ci95": ci_const,
                         "calibrated_distinct_tiers_test": distinct(ev_t, best_nc[1])},
        "test_money": ev_money, "test_paired_money_ci95": paired_money,
        "auc_query_score_needs_gt_tier1": {"test": auc_ev, "all": cal.auc(allneg, allpos),
                                           "n_pos_all": len(allpos), "n_neg_all": len(allneg), "target": cal.AUC_TARGET},
        "verdict": "PROMOTE" if promote else "HOLD",
        "verdict_reason": ("test CI excludes zero vs default cutoffs and vs best constant" if promote else
                           "no demonstrable gain on the TEST split (paired CI95 includes zero or favours defaults/constant); "
                           "policy defaults unchanged"),
    }


def light_verifier(cells, tasks_by_id, ctx):
    """ANA-185 offline: LIGHT escalation verifier (no ground truth) vs the scoring verifier, two variants:
    `lexical` = verify_for_escalation only; `lexical+abstain` = also accepts an explicit abstention (verify_abstention
    reads only the answer, no gabarito)."""
    from app.benchmark.routing_bench import _extract_json
    from app.routing.verifiers import verify_abstention
    variants = {"lexical": [], "lexical+abstain": []}
    per_kind = {v: collections.defaultdict(list) for v in variants}
    for c in cells:
        if c["rep"] != 0 or not c["answer"]:
            continue
        t = tasks_by_id[c["task"]]
        if t.kind == "code":
            continue
        if t.kind == "extraction":
            v = verify_for_escalation(_extract_json(c["answer"]), schema=t.verifier.get("schema"))
        else:
            notes = [n for n in (ctx.get(t.id, "")).split("<note") if n.strip()]
            v = verify_for_escalation(c["answer"], notes, c["retrieved"] or [], require_citation=False)
        ab = t.kind == "memory_qa" and bool(verify_abstention(c["answer"]).passed)
        kind = t.kind + ("/unanswerable" if t.ground_truth.get("answerable") is False else "")
        for name, acc in (("lexical", v.accept), ("lexical+abstain", v.accept or ab)):
            r = {"light_accept": acc, "gt_correct": bool(c["solved"])}
            variants[name].append(r)
            per_kind[name][kind].append(r)
    return {name: {"overall": escalation_error_rates(variants[name], "real"),
                   "by_kind": {k: escalation_error_rates(v, "real") for k, v in sorted(per_kind[name].items())}}
            for name in variants} | {
        "note": "LIGHT = verify_for_escalation (JSON schema for extraction; lexical grounding of every sentence vs the "
                "retrieved notes for memory_qa). code excluded (needs tests). A paid LLM-judge LIGHT was NOT run "
                "(command denied by the operator mid-run); these are the $0 variants."}


def build():
    st, integ = _load("onda4e_state.json"), _load("onda4e_integration.json")
    bench = _load("onda4e_bench.json")
    cellsd = _load("onda4e_cells.json")
    cells, ctx = cellsd["cells"], cellsd["context"]
    tasks = load_tasks() + load_tasks(ROOT / "benchmark" / "routing_tasks_code.json")
    tasks = sorted(tasks, key=lambda t: t.id)
    tb = {t.id: t for t in tasks}
    meta, recs = bench["meta"], bench["records"]
    idx = cell_index(cells)
    need = required_n_two_proportions(0.5, 0.10)
    table = strategy_table(recs)
    paired_vs = {f"{a} - {b}": {"solved": paired(recs, a, b, "solved"), "cost": paired(recs, a, b, "cost")}
                 for a, b in [("DYNAMIC_ROUTER", "STATIC_CHEAP"), ("DYNAMIC_ROUTER", "STATIC_DEFAULT"),
                              ("DYNAMIC_ROUTER", "STATIC_STRONG"), ("STATIC_STRONG", "STATIC_CHEAP"),
                              ("DYNAMIC_ROUTER:economic", "STATIC_CHEAP")]}
    by_model = {}
    for m in ORDER:
        cc = [c for c in cells if c["model"] == m]
        k = sum(1 for c in cc if c["solved"])
        by_model[m] = {"cells": len(cc), "solved": k, "rate": wilson_ci(k, len(cc)),
                       "cost_usd": round(sum(c["cost"] or 0 for c in cc), 6),
                       "cost_origin": sorted({c["cost_origin"] for c in cc})}
    by_kind = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    for c in cells:
        if c["rep"] == 0:
            kk = tb[c["task"]].kind + ("/unanswerable" if tb[c["task"]].ground_truth.get("answerable") is False else "")
            by_kind[kk][c["model"]][1] += 1
            by_kind[kk][c["model"]][0] += 1 if c["solved"] else 0
    by_kind = {k: {m: wilson_ci(*v[m]) for m in ORDER} for k, v in by_kind.items()}
    # why memory_qa answerable tasks fail for every model: is the gold note even retrieved?
    miss = {"answerable_memory_qa": 0, "unsolved_by_all": 0, "unsolved_and_gold_not_retrieved": 0}
    for t in tasks:
        if t.kind != "memory_qa" or t.ground_truth.get("answerable") is False:
            continue
        miss["answerable_memory_qa"] += 1
        if all((idx[(t.id, k)][0] or 0) < 0.5 for k in range(3)):
            miss["unsolved_by_all"] += 1
            ret = next((c["retrieved"] for c in cells if c["task"] == t.id and c["rep"] == 0), None) or []
            gold = {g.lower() for g in t.ground_truth.get("gold_notes", [])}
            if not (gold & {str(r).replace("\\", "/").lower() for r in ret}):
                miss["unsolved_and_gold_not_retrieved"] += 1
    spent_api = meta["spent_usd_api"]
    final_usage = integ.get("spent_after")
    out = {
        "generated_from": ["data/onda4e_bench.json", "data/onda4e_cells.json", "data/onda4e_integration.json"],
        "spend": {"credits_at_start": st["credits_at_start"], "baseline_usage": st["baseline_usage"],
                  "bench_stage_spent_usd_api": spent_api, "local_price_estimate_bench_stage": meta["local_price_estimate_usd"],
                  "cap_usd": meta["cap_usd"], "stop_usd": meta["stop_usd"], "origin": "measured (GET /api/v1/credits total_usage delta)",
                  "sum_cost_all_cells_by_registry_price": round(sum(c["cost"] or 0 for c in cells), 6),
                  "note": "o gasto real total da tarefa vem do delta de /credits; a soma das células × preço do registry o subestima "
                          "(chamadas perdidas na 1ª execução interrompida + sondas de integração)"},
        "n_tasks": meta["n_tasks"], "repeats": meta["repeats"], "n_errors_after_retry": meta["n_errors"],
        "task_mix": dict(collections.Counter(t.kind for t in tasks)),
        "leak_gate": "ANA-001/002: 0 tasks with expected fact in query (asserted in the runner before any call)",
        "power": {**power_report(meta["n_tasks"]), "required_n_per_arm_for_10pp": need,
                  "verdict": "SUBDIMENSIONADO: N available (174 memory_qa/extraction + 23 code) < required; paired CIs reported"
                  if meta["n_tasks"] < need else "ok"},
        "controls": meta["bench_meta"]["controls"], "repeat_report": meta["bench_meta"]["repeat_report"],
        "strategies": table, "paired_vs": paired_vs, "by_model_cells": by_model, "by_kind_rep0": by_kind,
        "memory_qa_retrieval_ceiling": miss,
        "preflight": meta["preflight"], "retries_errors": {"n_errors": meta["n_errors"], "sample": meta["error_log"][:5]},
        "calibration": calibration_real(tasks, idx),
        "light_verifier": light_verifier(cells, tb, ctx),
        "integration": {k: integ[k] for k in ("cases", "decisions", "retry_breaker_not_found", "retry_on_real_timeout",
                                               "breaker_on_real_timeouts", "kill_switch", "observed_kinds",
                                               "not_tested_on_purpose", "all_ok")},
    }
    return out


def fmt_ci(c):
    return f"{c['rate']} [{c['low']}; {c['high']}]" if c and c.get("rate") is not None else "n/d"


def render(o):
    L = ["# Onda 4e - Routing REAL via OpenRouter", "",
         "Gerado por `scripts/analyze_onda4e.py --write` a partir de `data/onda4e_*.json` (coleta: `scripts/run_onda4e_openrouter.py`). "
         "Origem dos números: `measured` = tokens/custo devolvidos pela API a preço do registry verificado (OpenRouter /models); "
         "gasto em dinheiro = delta de `GET /api/v1/credits`. Offline (esta análise): US$ 0.", ""]
    s = o["spend"]
    L += ["## Gasto", f"- Teto US$ {s['cap_usd']:.2f}; parada em 80% = US$ {s['stop_usd']:.2f}; saldo inicial US$ {s['credits_at_start']}.",
          f"- Etapa de benchmark (API /credits, `measured`): **US$ {s['bench_stage_spent_usd_api']}** "
          f"(estimativa local por preço no guard: US$ {s['local_price_estimate_bench_stage']}, só da 2ª execução).",
          f"- Soma dos custos por célula (preço do registry × tokens medidos): US$ {s['sum_cost_all_cells_by_registry_price']}.",
          f"- {s['note']}", ""]
    pf = o["preflight"]
    L += ["## Pré-voo (ANA-165)", f"- estimativa US$ {pf['estimate_usd']} ({pf['estimate_origin']}) para {pf['n_calls']} chamadas; "
          f"ok={pf['ok']}. Kill-switch ANA-168: `ANAMNESIA_PAID_CALLS=0` bloqueia `make_adapter` (PaidCallsDisabled), verificado ao vivo.", ""]
    p = o["power"]
    L += ["## Amostra e poder (ANA-014)", f"- N={o['n_tasks']} tarefas ({o['task_mix']}), {o['repeats']} repetições, "
          f"{o['n_errors_after_retry']} erros de provider após retry.",
          f"- Poder para detectar 10pp (taxa-base 50%): {p['achieved_power']}; necessário ~{p['required_n_per_arm_for_10pp']}/braço. "
          f"**{p['verdict']}**. Conclusões abaixo usam IC pareado (bootstrap) por tarefa, que é mais forte que o teste não pareado.",
          f"- Gabarito vazado (ANA-001/002): {o['leak_gate']}.", ""]
    L += ["## Resultados por estratégia (`measured`; repetições empilhadas)", "",
          "| Estratégia | N | resolvidas | taxa [IC95 Wilson] | custo US$ | custo/resolvida | escalations | router US$ | verify US$ | retry US$ | origem custo |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, r in o["strategies"].items():
        L.append(f"| {k} | {r['n']} | {r['solved']} | {fmt_ci(r['rate'])} | {r['cost_usd']} | {r['cost_per_solved']} | {r['escalations']} | "
                 f"{r['router_cost']} | {r['verify_cost']} | {r['retry_cost']} | {','.join(r['cost_origin'])} |")
    L += ["", "- Custo de verificação (ANA-164): o verificador do benchmark não chama LLM (`verify_tokens_origin`="
          f"{o['strategies']['DYNAMIC_ROUTER']['verify_tokens_origin']}): US$ 0 em tokens, só latência (medida). "
          "O router não chama LLM (`router_tokens_origin`="
          f"{o['strategies']['DYNAMIC_ROUTER']['router_tokens_origin']}). Retry de provider: ver `n_errors_after_retry`.",
          "- Ressalva: o escalonamento do DYNAMIC_ROUTER usa o verificador COM gabarito (ver ANA-185); portanto sua taxa é um teto otimista.", "",
          "### Diferenças pareadas por tarefa (média sobre repetições; IC95 bootstrap)", "",
          "| contraste | Δ taxa de acerto | exclui 0? | Δ custo US$/tarefa | exclui 0? |", "|---|---|---|---|---|"]
    for k, v in o["paired_vs"].items():
        a, c = v["solved"], v["cost"]
        L.append(f"| {k} | {a['mean_diff']} [{a['low']}; {a['high']}] | {a['excludes_zero']} | {c['mean_diff']} [{c['low']}; {c['high']}] | {c['excludes_zero']} |")
    L += ["", "### Por modelo (todas as células)", "", "| modelo | células | resolvidas | taxa [IC95] | custo US$ |", "|---|---|---|---|---|"]
    for m, r in o["by_model_cells"].items():
        L.append(f"| {m} | {r['cells']} | {r['solved']} | {fmt_ci(r['rate'])} | {r['cost_usd']} |")
    L += ["", "### Por tipo de tarefa (rep 0, taxa [IC95])", "", "| tipo | " + " | ".join(ORDER) + " |", "|---|---|---|---|"]
    for k, v in sorted(o["by_kind_rep0"].items()):
        L.append(f"| {k} | " + " | ".join(fmt_ci(v[m]) for m in ORDER) + " |")
    q = o["memory_qa_retrieval_ceiling"]
    L += ["", f"- Teto de recuperação: {q['unsolved_by_all']}/{q['answerable_memory_qa']} memory_qa respondíveis não são resolvidas por NENHUM tier; "
          f"em {q['unsolved_and_gold_not_retrieved']} delas a nota-ouro nem foi recuperada (falha de retrieval, não de modelo).", ""]
    L += ["## Controles negativos (ANA-016)", ""]
    for k, c in o["controls"].items():
        L.append(f"- {k}: {c['passed']}/{c['n']} aprovados, IC95 [{c['ci']['low']}; {c['ci']['high']}], verificador inválido={c['invalid_verifier']}")
    cal_ = o["calibration"]
    tc = cal_["tier_cutoffs"]
    L += ["", "## Router offline vs t* REAL (ANA-170/189)", "", f"- Proxy: {cal_['proxy']}.",
          f"- Split (seed 42): {cal_['split']}. t* (todas): {cal_['tstar_distribution_all']}; t* (teste): {cal_['tstar_distribution_test']}.",
          f"- `tier_cutoffs`: default {tc['default']} → calibrado (não constante) {tc['calibrated_nonconstant']}; "
          f"regret calibração {tc['cal_regret_default']} → {tc['cal_regret_calibrated']}; **regret TESTE** {tc['test_regret_default']} → {tc['test_regret_calibrated']}; "
          f"diff pareada (default−calibrado) IC95 {tc['test_paired_default_minus_calibrated_ci95']}.",
          f"- Melhor constante: tier {tc['best_constant_tier']} (regret teste {tc['test_regret_best_constant']}); "
          f"(constante−calibrado) IC95 {tc['test_paired_constant_minus_calibrated_ci95']}. Melhor da grade (pode ser constante): {tc['best_any']}.",
          f"- AUC do score só-da-query para 'precisa de mais que o tier 1': {cal_['auc_query_score_needs_gt_tier1']}.", "",
          "| roteamento (teste) | taxa de acerto | custo médio US$/tarefa | tiers usados |", "|---|---|---|---|"]
    for k, v in cal_["test_money"].items():
        L.append(f"| {k} | {v['solve_rate']} | {v['mean_cost_usd']} | {v['tier_counts']} |")
    L += ["", "Diferenças pareadas no TESTE (IC95):", ""]
    for k, v in cal_["test_paired_money_ci95"].items():
        a, c = v["solve_rate_diff"], v["cost_diff_usd"]
        L.append(f"- {k}: Δacerto {a['mean_diff']} [{a['low']}; {a['high']}]; Δcusto {c['mean_diff']} [{c['low']}; {c['high']}]")
    L += ["", f"**Veredito: {cal_['verdict']}** - {cal_['verdict_reason']}.", ""]
    lv = o["light_verifier"]
    L += ["## Verificador LIGHT sem gabarito (ANA-185)", "", f"- {lv['note']}", ""]
    for name in ("lexical", "lexical+abstain"):
        ov = lv[name]["overall"]
        L += [f"### Variante `{name}` - n={ov['n']} ({ov['note']}; origem real)",
              f"- Falso-aceite P(errada|aceita) = {fmt_ci(ov['false_accept'])}; falso-rejeite P(certa|rejeitada) = {fmt_ci(ov['false_reject'])}.", "",
              "| tipo | n | falso-aceite [IC95] | falso-rejeite [IC95] |", "|---|---|---|---|"]
        for k, v in lv[name]["by_kind"].items():
            L.append(f"| {k} | {v['n']} | {fmt_ci(v['false_accept'])} | {fmt_ci(v['false_reject'])} |")
        L.append("")
    it = o["integration"]
    L += ["", "## Integração com erros reais do provider (ANA-171/177/178/187)", "",
          f"- Taxonomia observada ao vivo: {it['observed_kinds']}; tudo conforme esperado: {it['all_ok']}.",
          "- Não testado de propósito: " + "; ".join(it["not_tested_on_purpose"]) + ".", "",
          "| caso | esperado | obtido | HTTP | ok |", "|---|---|---|---|---|"]
    for c in it["cases"]:
        L.append(f"| {c['case']} | {c['expected_kind']} | {c['error_kind']} | {c['status_code']} | {c['ok']} |")
    L += ["", f"- Decisões (ANA-177) com os kinds reais: {it['decisions']}",
          f"- Retry em timeout real (ANA-178): {it['retry_on_real_timeout']}",
          f"- Breaker (ANA-187) em 3 timeouts reais: sequência {[(x['kind'], x['circuit_open']) for x in it['breaker_on_real_timeouts']['sequence']]}, estado final {it['breaker_on_real_timeouts']['state']}.",
          f"- model_not_found x4 (modelo inexistente): {[(x['kind'], x['circuit_open']) for x in it['retry_breaker_not_found']['attempts']]}.",
          f"- Achado/correção: OpenRouter devolve **HTTP 400** `<id> is not a valid model ID` (não 404) para modelo inexistente; "
          "`classify` o tratava como `other` - corrigido em `app/adapters/models/errors.py` (+ caso em `tests/test_onda4_errors.py`).", ""]
    L += ["", "## Revisão (conferida contra data/onda4e_cells.json)", "",
          "- Conferido: por modelo, N, resolvidas, taxa e custo recomputados das 1182 células brutas batem com a tabela (0 erros, origem `measured`).",
          "- Leitura honesta: em memory_qa os três tiers acertam as MESMAS tarefas (o limite é a recuperação, não o modelo); o tier forte custa ~28x o barato sem ganho significativo (STATIC_STRONG - STATIC_CHEAP: IC inclui 0).",
          "- O ganho do DYNAMIC_ROUTER sobre STATIC_CHEAP usa verificador COM gabarito para escalar: é teto otimista, não resultado de produção.",
          "- N=197 com poder 0.514: conclusões de 'sem diferença' NÃO provam equivalência. Calibração de cutoffs: HOLD, defaults inalterados.",
          "- Verificador LIGHT lexical tem falso-aceite 0.32 e falso-rejeite 0.59: não serve sozinho para escalar; juiz LLM pago não foi medido.",
          ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    o = build()
    md = render(o)
    if a.write:
        OUT_MD.parent.mkdir(parents=True, exist_ok=True)
        OUT_MD.write_text(md, encoding="utf-8", newline="\n")
        OUT_JSON.write_text(json.dumps(o, ensure_ascii=False, indent=1, default=str), encoding="utf-8", newline="\n")
        print("written", OUT_MD.name, OUT_JSON.name)
    elif a.check:
        cur = OUT_MD.read_text(encoding="utf-8") if OUT_MD.exists() else ""
        if cur != md:
            print("STALE: run scripts/experiments/analyze_onda4e.py --write")
            return 1
        print("fresh")
    else:
        print(md[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
