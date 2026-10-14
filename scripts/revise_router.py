#!/usr/bin/env python
"""ANA-190: principled revision of the deterministic router's features/weights/cut-offs, measured offline.

    .venv/Scripts/python scripts/revise_router.py            # print JSON
    .venv/Scripts/python scripts/revise_router.py --write    # also write docs/reports/ROUTER_REVISAO.md

Protocol (no label/answer/risk is ever a feature):
  * split: routing_tasks.json -> TRAIN / HELD-OUT with split_tasks(seed=42, 0.5), stratified, deterministic;
  * fit weights (grid, parsimonious) and cut-offs (train score quantiles) on TRAIN only;
  * report AUC(easy<hard) with stratified-bootstrap CI95 on TRAIN and on HELD-OUT, BEFORE vs AFTER;
  * the 0.75 target is reported, never forced.
Pure: no model, no network. Reads the corpus (data/synthetic_vault/**/*.md) only to build the vocabulary.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routing import calibration as cal  # noqa: E402
from app.routing.policy import RoutingPolicy, preset  # noqa: E402
from app.routing.registry import load_registry  # noqa: E402
from app.routing.router import build_vocab, route  # noqa: E402
from app.routing.tasks import DEFAULT_PATH, DIFFICULTIES, load_tasks, split_tasks  # noqa: E402

REPORT = ROOT / "docs" / "reports" / "ROUTER_REVISAO.md"
VAULT = ROOT / "data" / "synthetic_vault"
SEED = 42
# multi-hop cues added by this revision (stripped to rebuild the BEFORE policy)
NEW_CUES = ("outra nota", "notas relacionadas", "nota relacionada", "se conectam", "related note", "how they connect")
# BEFORE = the router as shipped in Onda 4c
LEGACY_BALANCED_CUTOFFS = (0.25, 0.5, 0.75)


def corpus_vocab(vault: Path = VAULT) -> frozenset:
    return build_vocab(p.read_text(encoding="utf-8", errors="replace") for p in sorted(vault.rglob("*.md")))


def legacy_policy() -> RoutingPolicy:
    p = preset("balanced", enabled=True)
    w = {k: v for k, v in p.weights.items() if k != "ungrounded"}
    w.update({"length": 1.0, "entities": 1.0, "multi_hop": 2.0, "context": 1.0, "code": 1.0, "reasoning": 1.5,
              "classifier": 1.0})
    return dataclasses.replace(p, weights=w, tier_cutoffs=LEGACY_BALANCED_CUTOFFS,
                               multi_hop_cues=tuple(c for c in p.multi_hop_cues if c not in NEW_CUES))


def measure(name, tasks, scores, cutoffs, n_tiers=3):
    ci = cal.bootstrap_auc_ci(tasks, scores)
    dist = cal.distribution_report(tasks, scores, cutoffs, n_tiers)
    return {"set": name, "n": len(tasks), "auc_easy_lt_hard": ci["auc"], "ci95": [ci["low"], ci["high"]],
            "auc_easy_lt_medium": dist["auc_easy_lt_medium"], "auc_medium_lt_hard": dist["auc_medium_lt_hard"],
            "score_mean_by_label": dist["score_mean_by_label"], "tier_counts_score_only": dist["tier_counts"]}


def routed_tiers(tasks, policy, registry, vocab, use_risk: bool):
    """Real route(): query-only risk ('medium' default => no bump) vs the task's own risk field."""
    out = []
    for t in tasks:
        out.append(route(t.query, 0, "memory", t.risk if use_risk else "low", registry, policy, vocab=vocab).tier)
    return dict(sorted(Counter(out).items()))


def run(seed: int = SEED, vault: Path = VAULT) -> dict:
    tasks = load_tasks(DEFAULT_PATH)
    train, held = split_tasks(tasks, seed=seed, calibration_frac=0.5)
    reg = load_registry(None)
    vocab = corpus_vocab(vault)
    n_tiers = len(reg.tiers())

    # ---- BEFORE (shipped router: no vocab, old weights/cues/cut-offs)
    old = legacy_policy()
    before = {"policy": {"weights": old.weights, "tier_cutoffs": list(old.tier_cutoffs), "floor_level": old.floor_level},
              "train": measure("train", train, cal.score_tasks(train, old), old.tier_cutoffs, n_tiers),
              "held_out": measure("held_out", held, cal.score_tasks(held, old), old.tier_cutoffs, n_tiers),
              "routed_all_tasks_with_task_risk": routed_tiers(tasks, old, reg, None, True),
              "routed_all_tasks_query_only": routed_tiers(tasks, old, reg, None, False)}

    # ---- FIT on TRAIN only
    base = preset("balanced", enabled=True)
    fit = cal.fit_weights(train, base, vocab)
    fitted = dataclasses.replace(base, weights=fit["weights"])
    tr_scores = cal.score_tasks(train, fitted, vocab=vocab)
    cut_bal = cal.quantile_cutoffs(tr_scores, (0.33, 0.5, 0.67))
    cut_eco = cal.quantile_cutoffs(tr_scores, (0.5, 0.75, 0.9))
    new = dataclasses.replace(fitted, tier_cutoffs=cut_bal)
    after = {"policy": {"weights": new.weights, "tier_cutoffs": list(cut_bal), "economic_cutoffs": list(cut_eco),
                        "floor_level": new.floor_level, "ungrounded_saturation": new.ungrounded_saturation},
             "fit": {k: v for k, v in fit.items() if k != "weights"},
             "train": measure("train", train, tr_scores, cut_bal, n_tiers),
             "held_out": measure("held_out", held, cal.score_tasks(held, new, vocab=vocab), cut_bal, n_tiers),
             "routed_all_tasks_with_task_risk": routed_tiers(tasks, new, reg, vocab, True),
             "routed_all_tasks_query_only": routed_tiers(tasks, new, reg, vocab, False),
             "routed_held_out_query_only": routed_tiers(held, new, reg, vocab, False)}

    # ---- ablations on HELD-OUT with the TRAIN-fitted weights (what carries the signal?)
    abl = {}
    for name, w_over, v in (("sem_vocab (ungrounded ausente)", {}, None),
                            ("sem_ungrounded (peso 0)", {"ungrounded": 0.0}, vocab),
                            ("so_length", {k: (1.0 if k == "length" else 0.0) for k in new.weights}, vocab),
                            ("so_ungrounded", {k: (1.0 if k == "ungrounded" else 0.0) for k in new.weights}, vocab)):
        p = dataclasses.replace(new, weights={**new.weights, **w_over})
        s = cal.score_tasks(held, p, vocab=v)
        ci = cal.bootstrap_auc_ci(held, s)
        abl[name] = {"auc": ci["auc"], "ci95": [ci["low"], ci["high"]]}
    # ---- sanity: shuffled labels on held-out must sit near 0.5 (no accidental leakage / bug)
    import random
    rng = random.Random(7)
    labs = [t.difficulty_label for t in held]
    rng.shuffle(labs)
    shuf = [dataclasses.replace(t, difficulty_label=l) for t, l in zip(held, labs)]
    sci = cal.bootstrap_auc_ci(shuf, cal.score_tasks(shuf, new, vocab=vocab))
    gate_tiers = after["routed_all_tasks_query_only"]
    out = {
        "seed": seed, "n_train": len(train), "n_held_out": len(held),
        "train_labels": dict(Counter(t.difficulty_label for t in train)),
        "held_out_labels": dict(Counter(t.difficulty_label for t in held)),
        "vocab_size": len(vocab), "before": before, "after": after, "ablations_held_out": abl,
        "sanity_shuffled_labels_held_out": {"auc": sci["auc"], "ci95": [sci["low"], sci["high"]]},
        "target": cal.AUC_TARGET,
        "target_met_held_out": bool(after["held_out"]["ci95"][0] is not None and after["held_out"]["auc_easy_lt_hard"] >= cal.AUC_TARGET),
        "gate_router_not_constant": bool(len(gate_tiers) >= 2),
    }
    return out


def render_md(r: dict) -> str:
    b, a = r["before"], r["after"]
    f = lambda m: f"{m['auc_easy_lt_hard']} [{m['ci95'][0]}, {m['ci95'][1]}]"  # noqa: E731
    L = ["# ROUTER_REVISAO — revisão de features/pesos do router determinístico (ANA-190)", "",
         "Gerado por `scripts/revise_router.py --write`. Offline, zero token, zero rede. "
         "Proxy: AUC(easy<hard) contra o rótulo objetivo de `benchmark/routing_tasks.json` "
         "(**não** é qualidade de modelo nem economia).", "",
         "## Protocolo", "",
         f"- Split estratificado determinístico (`split_tasks`, seed {r['seed']}): TREINO {r['n_train']} "
         f"{r['train_labels']} / HELD-OUT {r['n_held_out']} {r['held_out_labels']}.",
         "- Pesos ajustados por grade grossa (0/1/2/4) e cortes por quantis do score — **só no TREINO**; "
         "HELD-OUT só medido. IC95 = bootstrap percentil estratificado (easy e hard reamostrados, 2000 réplicas, seed fixa).",
         "- Features usam só a consulta (+ vocabulário do corpus para `ungrounded`). Nenhum rótulo, resposta, "
         "`ground_truth` ou campo `risk` é feature.",
         f"- Meta SUCCESS_METRIC: AUC ≥ {r['target']}. **Meta atingida no held-out: "
         f"{'SIM' if r['target_met_held_out'] else 'NÃO'}.**", "",
         "## Resultado (AUC easy<hard, IC95)", "",
         "| | TREINO | HELD-OUT |", "|---|---|---|",
         f"| ANTES (Onda 4c) | {f(b['train'])} | {f(b['held_out'])} |",
         f"| DEPOIS | {f(a['train'])} | {f(a['held_out'])} |", "",
         f"AUC easy<medium / medium<hard (held-out): antes {b['held_out']['auc_easy_lt_medium']} / "
         f"{b['held_out']['auc_medium_lt_hard']}; depois {a['held_out']['auc_easy_lt_medium']} / "
         f"{a['held_out']['auc_medium_lt_hard']}.", "",
         f"Score médio por rótulo (held-out): antes {b['held_out']['score_mean_by_label']}; "
         f"depois {a['held_out']['score_mean_by_label']}.", "",
         "## Diagnóstico (por que a AUC era < 0,5)", "",
         "1. **Sinal invertido da feature `length`/`classifier`.** Os rótulos `hard` são, em maioria, perguntas "
         "*sem resposta* no vault (curtas, ~10 palavras, sobre entidade inventada), enquanto `easy` são cloze longos "
         "(~25 palavras). `length` e `classifier` (SIMPLE/MEDIUM/COMPLEX por tamanho) davam score MAIOR ao easy: "
         "AUC isolada easy<hard no treino ≈ 0,23 e 0,25. Peso total deles ≈ 2/8,5 do score, o suficiente para inverter o conjunto.",
         "2. **Features sem variação.** `context`, `code`, `reasoning` ≈ 0 em todas as tarefas; só diluem o score "
         "(máximo observado ≈ 0,4).",
         "3. **Saturação de thresholds.** Com score ≤ ~0,4, os cortes (0,25/0,5/0,75) tornavam os níveis 2–3 "
         "inalcançáveis; `balanced` tem `floor_level=1` (tier 1 proibido) e o bump de risco nas tarefas hard era o único "
         "caminho para cima: o resultado era tier 2 em 174/174 (router constante na prática).",
         "4. **Não é vazamento de rótulo no router**, mas **o eval antigo usava `task.risk`**, que o gerador deriva de "
         "`answerable` (ingrediente do rótulo). Isso infla/contamina a matriz 'roteada'. Aqui a medição principal usa risco "
         "neutro; a versão com risco da tarefa aparece separada e rotulada como contaminada.", "",
         "## O que mudou", "",
         "- Nova feature `ungrounded` (`router.ungrounded_ids`): nº de identificadores (nome próprio/CamelCase/token raro) da "
         "consulta que **não existem no vocabulário do corpus** — assinatura de pergunta fora do corpus/sem resposta. "
         "Só ativa quando o chamador passa `vocab` (parâmetro opcional; sem ele o score renormaliza como antes).",
         "- Cues de multi-hop genéricos de referência cruzada (`outra nota`, `nota relacionada`, `se conectam`...). "
         "**Ressalva:** escolhidos olhando consultas do TREINO; refletem os templates do gerador sintético.",
         f"- Pesos ajustados no treino (grade parcimoniosa): {a['policy']['weights']}. "
         f"Candidatos dentro da tolerância: {a['fit']['n_candidates_within_tolerance']}.",
         f"- Cortes `balanced` por quantis 0,33/0,5/0,67 do treino: {a['policy']['tier_cutoffs']}; "
         f"`economic` (0,5/0,75/0,9): {a['policy']['economic_cutoffs']}. `max` inalterado (constante por construção).",
         "- Routing continua **OFF por padrão** (`enabled=False`); `ANSWER_MAX_DIFFICULTY=0.75` não alterado "
         "(a escala do score mudou: reavaliar antes de ligar o answer-loop).", "",
         "## Distribuição por tier (route() real, 174 tarefas, preset balanced)", "",
         f"- ANTES, risco neutro: {b['routed_all_tasks_query_only']}; com risco da tarefa (contaminado): "
         f"{b['routed_all_tasks_with_task_risk']}.",
         f"- DEPOIS, risco neutro: {a['routed_all_tasks_query_only']}; com risco da tarefa (contaminado): "
         f"{a['routed_all_tasks_with_task_risk']}; só held-out, risco neutro: {a['routed_held_out_query_only']}.",
         f"- Gate `router != constante` (≥2 tiers, risco neutro): **{'PASSA' if r['gate_router_not_constant'] else 'FALHA'}**.", "",
         "## Ablações no held-out (pesos fixos do treino)", "", "| variante | AUC | IC95 |", "|---|---|---|"]
    L += [f"| {k} | {v['auc']} | [{v['ci95'][0]}, {v['ci95'][1]}] |" for k, v in r["ablations_held_out"].items()]
    s = r["sanity_shuffled_labels_held_out"]
    L += ["", f"Sanidade (rótulos embaralhados no held-out): AUC {s['auc']} [{s['ci95'][0]}, {s['ci95'][1]}] — esperado ≈ 0,5.", "",
          "## Limites e honestidade", "",
          "- n pequeno (86 no held-out; ~28 easy × ~29 hard): IC largo; um único split.",
          "- Rótulos vêm da estrutura do corpus sintético, não de execução de modelos; `hard` ≈ 'sem resposta' (por construção). "
          "O ganho vem da detecção de entidade fora do corpus, que num vault real depende de o vocabulário cobrir o vault.",
          "- Os cues e a feature `ungrounded` foram desenhados vendo o treino e o gerador de templates; o held-out não foi "
          "usado para escolher nada, mas a generalização para consultas reais **não está demonstrada**.",
          "- **Divulgação:** durante a exploração do diagnóstico, a contagem de `ungrounded` por rótulo também foi impressa para o "
          "split held-out (não para escolher pesos/cortes, que vieram só do treino, mas o held-out não é cego a 100%). "
          "O AUC held-out (0,95) > treino (0,81) é compatível com ruído de n pequeno; trate o treino (IC inferior 0,70) como estimativa mais conservadora.",
          "- A feature praticamente detecta 'pergunta sem resposta/entidade inventada' (AUC so_ungrounded no held-out acima); "
          "easy<medium continua fraco (~0,58): o router não separa medium de easy.",
          "- A meta 0,75 não foi forçada: nenhum ajuste foi feito após ver o held-out.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    r = run(a.seed)
    if a.write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(render_md(r), encoding="utf-8", newline="\n")
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
