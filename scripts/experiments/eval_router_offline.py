#!/usr/bin/env python
"""ANA-170: evaluate the deterministic router OFFLINE against the objective difficulty labels of
benchmark/routing_tasks.json. Pure: no model calls, no network, no keys.

    .venv/Scripts/python scripts/experiments/eval_router_offline.py            # print JSON
    .venv/Scripts/python scripts/experiments/eval_router_offline.py --write    # also write data/reports-out/ONDA4_ROUTER_OFFLINE.md
    ... --check   # exit 1 when the gate fails (router is constant)

Gate (ANA-170): router != constant, i.e. >= 2 distinct tiers and tier entropy > 0 for the evaluated preset.
Target (SUCCESS_METRIC, reported separately from the gate): AUC(easy<hard) >= 0.75.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.routing import calibration as cal  # noqa: E402
from app.routing.policy import PRESET_NAMES, preset  # noqa: E402
from app.routing.registry import load_registry  # noqa: E402
from app.routing.router import route  # noqa: E402
from app.routing.tasks import DEFAULT_PATH, DIFFICULTIES, load_tasks  # noqa: E402

REPORT = ROOT / "data" / "reports-out" / "ONDA4_ROUTER_OFFLINE.md"


def evaluate(tasks, registry, preset_name: str) -> dict:
    """Score + route every task with `preset_name` (routing enabled in-memory only)."""
    policy = preset(preset_name, enabled=True)
    n_tiers = len(registry.tiers())
    scores = cal.score_tasks(tasks, policy)
    raw = cal.distribution_report(tasks, scores, policy.tier_cutoffs, n_tiers)
    tiers = [route(t.query, 0, "memory", t.risk, registry, policy).tier for t in tasks]
    counts = Counter(tiers)
    tier_order = registry.tiers()
    conf = [[0] * len(tier_order) for _ in DIFFICULTIES]
    for t, tr in zip(tasks, tiers):
        conf[cal.LABEL_RANK[t.difficulty_label]][tier_order.index(tr)] += 1
    ent = cal.entropy_bits(counts)
    return {
        "preset": preset_name, "policy_version": policy.version_hash()[:12],
        "tier_cutoffs": list(policy.tier_cutoffs), "floor_level": policy.floor_level,
        "score_distribution": raw,
        "routed": {  # real route(): includes risk bump + floor, registry tiers
            "tier_counts": dict(sorted(counts.items())), "tier_entropy_bits": ent,
            "distinct_tiers": len(counts), "confusion_label_x_tier": conf, "tiers": tier_order},
        "gate_router_not_constant": bool(len(counts) >= 2 and ent > 0),
        "auc_target_met": (raw["auc_easy_lt_hard"] or 0) >= cal.AUC_TARGET,
    }


def run(tasks_path=DEFAULT_PATH, registry_path=None, seed: int = 42) -> dict:
    tasks = load_tasks(tasks_path)
    reg = load_registry(registry_path)
    out = {
        "n_tasks": len(tasks), "tasks_path": str(Path(tasks_path).name),
        "label_counts": dict(Counter(t.difficulty_label for t in tasks)),
        "risk_counts": dict(Counter(t.risk for t in tasks)),
        "registry_tiers": reg.tiers(),
        "presets": {p: evaluate(tasks, reg, p) for p in PRESET_NAMES},
        "calibration": cal.calibrate(tasks, preset("balanced", enabled=True), seed=seed,
                                     n_tiers=len(reg.tiers())),
        "caveat": ("Labels come from corpus structure (multi_hop, #gold notes, unanswerable, paraphrase, "
                   "duplicates, length). Some of those signals are invisible to a query-only router; this "
                   "measures router-vs-label agreement, not router-vs-t* (that needs real model runs)."),
    }
    out["gate_default_preset"] = out["presets"]["balanced"]["gate_router_not_constant"]
    return out


def _fmt_conf(m, cols):
    head = "| label \\ tier | " + " | ".join(f"t{c}" for c in cols) + " |\n|---|" + "---|" * len(cols)
    rows = [f"| {d} | " + " | ".join(str(x) for x in r) + " |" for d, r in zip(DIFFICULTIES, m)]
    return head + "\n" + "\n".join(rows)


def render_md(r: dict) -> str:
    L = ["# Onda 4c — Router offline (ANA-170 / ANA-189)", "",
         "Gerado por `scripts/eval_router_offline.py --write`. Offline, zero token, zero rede. "
         "Dados: `benchmark/routing_tasks.json` (rótulos objetivos de dificuldade). "
         "**Nenhum número aqui é economia nem qualidade de modelo.**", "",
         f"- Tarefas: {r['n_tasks']} — rótulos {r['label_counts']} — risco {r['risk_counts']}",
         f"- Tiers no registry: {r['registry_tiers']}", f"- Ressalva: {r['caveat']}", ""]
    g = r["gate_default_preset"]
    L += [f"## Gate ANA-170: router != constante (preset `balanced`, o padrão): **{'PASSA' if g else 'FALHA'}**", ""]
    L += ["| preset | AUC easy<hard | AUC easy<med | AUC med<hard | tiers (roteado) | entropia (bits) | gate | AUC>=0,75 |",
          "|---|---|---|---|---|---|---|---|"]
    for p, e in r["presets"].items():
        d = e["score_distribution"]
        L.append(f"| {p} | {d['auc_easy_lt_hard']} | {d['auc_easy_lt_medium']} | {d['auc_medium_lt_hard']} | "
                 f"{e['routed']['tier_counts']} | {e['routed']['tier_entropy_bits']} | "
                 f"{'ok' if e['gate_router_not_constant'] else 'FALHA'} | {'sim' if e['auc_target_met'] else 'não'} |")
    L += [""]
    for p, e in r["presets"].items():
        d = e["score_distribution"]
        L += [f"### Preset `{p}` (cortes {e['tier_cutoffs']}, floor_level {e['floor_level']}, política {e['policy_version']})",
              f"- Score médio por rótulo: {d['score_mean_by_label']}",
              f"- Níveis (só score, sem risco/floor): {d['level_counts']}",
              "- Matriz de confusão do roteamento real (linhas = rótulo; colunas = tier escolhido, com bump de risco):", "",
              _fmt_conf(e["routed"]["confusion_label_x_tier"], e["routed"]["tiers"]), ""]
    c = r["calibration"]
    tc, am = c["tier_cutoffs"], c["answer_max_difficulty"]
    L += ["## ANA-189 — calibração em split (seed %d: %d calibração / %d eval)" % (c["seed"], c["n_calibration"], c["n_eval"]),
          f"- Proxy: {c['proxy_note']}",
          f"- `tier_cutoffs`: default {tc['default']} → calibrado {tc['calibrated']}; regret na calibração "
          f"{tc['cal_regret_default']} → {tc['cal_regret_calibrated']}; **regret no EVAL** "
          f"{tc['eval_regret_default']} → {tc['eval_regret_calibrated']}; diff pareada IC95 {tc['eval_paired_diff_ci95']}",
          f"- Melhor roteador CONSTANTE (tier idx {tc['best_constant_tier_index']}): regret no EVAL "
          f"{tc['eval_regret_best_constant']}; candidato vs constante (const − cand) IC95 {tc['eval_paired_diff_vs_constant_ci95']}",
          f"- `ANSWER_MAX_DIFFICULTY`: default {am['default']} → calibrado {am['calibrated']}; perda no EVAL "
          f"{am['eval_loss_default']} → {am['eval_loss_calibrated']}; diff pareada IC95 {am['eval_paired_diff_ci95']}",
          f"- AUC easy<hard no eval: {c['auc_eval_easy_lt_hard']}",
          f"- **Veredito: {c['verdict']}** — {c['verdict_reason']}.", "",
          "Top-5 da grade de cortes na calibração:", "", "| cortes | regret | entropia | tiers |", "|---|---|---|---|"]
    L += [f"| {x['tier_cutoffs']} | {x['mean_regret']} | {x['entropy_bits']} | {x['distinct_tiers']} |"
          for x in tc["top5_on_calibration"]]
    L += ["", "Os defaults (`policy.py`, `ANSWER_MAX_DIFFICULTY=0.75`) **não foram alterados**.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ANA-170 offline router evaluation")
    ap.add_argument("--tasks", default=str(DEFAULT_PATH))
    ap.add_argument("--registry", default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--write", action="store_true", help=f"write {REPORT.relative_to(ROOT)}")
    ap.add_argument("--check", action="store_true", help="exit 1 if the gate (router != constant) fails")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    r = run(a.tasks, a.registry, a.seed)
    if a.write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(render_md(r), encoding="utf-8", newline="\n")
    if not a.quiet:
        slim = {k: v for k, v in r.items() if k != "calibration"}
        slim["calibration_verdict"] = r["calibration"]["verdict"]
        print(json.dumps(slim, ensure_ascii=False, indent=1)[:6000])
    return 1 if (a.check and not r["gate_default_preset"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
