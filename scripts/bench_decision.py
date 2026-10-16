"""Benchmark do Decision Engine (ANAM-043): JEV-only, Laya-only, Laya→JEV, JEV→Laya, ensemble e adaptive.

    python scripts/bench_decision.py            # roda e escreve docs/bench/decision-engine.{md,json}

DADOS: os mesmos de scripts/bench_laya.py — `benchmark/laya_labeled.json` (192 pares consulta×trecho do corpus
SINTÉTICO, entidades inventadas) e as pontuações REAIS do Laya já gravadas em
`docs/bench/anam-042-laya-scores.json` (braço multilingual_only). NENHUM dado do vault real.

O QUE É MEDIDO E O QUE NÃO É (rótulos MEASURED / ESTIMATED / UNKNOWN):
  * Laya: as probabilidades são REPLAY do que o Laya real produziu em ANAM-042 (MEASURED lá); aqui não se
    recarrega o modelo. A latência por candidato (227,6 ms/cand. em lote, CPU) vem dessa mesma execução.
  * JEV: o JEV REAL (TypeSafe) NÃO é acessível => "JEV real: não medido". Usa-se um JEV FAKE determinístico
    (proxy lexical + sigmoide; ver FakeJev) que implementa a mesma interface de `JevService.evaluate`. Ele
    exercita o código dos providers/estratégias e CONTA chamadas, mas a QUALIDADE (P/R/F1) das linhas que
    dependem do JEV é a do proxy, não a do JEV. Nem o Colibrì local estava rodando.
  * Custo JEV em tokens = modelo 340·req + 209·perguntas (ESTIMATED); USD do JEV real = UNKNOWN.
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.decision import DecisionEngine, DecisionRequest, Item  # noqa: E402
from app.decision.analysis import auc, divergence, percentile, prf  # noqa: E402
from app.decision.config import DecisionConfig, Thresholds, load_config  # noqa: E402
from app.decision.cost import estimate_jev_tokens  # noqa: E402
from app.decision.telemetry import DecisionHistory  # noqa: E402
from app.decision.types import MEASURED  # noqa: E402,F401
from app.services.laya_decider import LayaAnswer  # noqa: E402

DATA = ROOT / "benchmark" / "laya_labeled.json"
SCORES = ROOT / "docs" / "bench" / "anam-042-laya-scores.json"
OUT_MD = ROOT / "docs" / "bench" / "decision-engine.md"
OUT_JSON = ROOT / "docs" / "bench" / "decision-engine.json"

_TOK = re.compile(r"[a-z0-9][a-z0-9._-]{3,}")


def lexical(q: str, note: str) -> float:   # idêntico a scripts/bench_laya.py
    qs, ns = set(_TOK.findall(q.lower())), set(_TOK.findall(note.lower()))
    return len(qs & ns) / max(1, len(qs))


# ---------------------------------------------------------------------------------- doubles
class _Cfg:
    model, mode, injection_threshold = "FAKE-jev-lexical-proxy", "performance", 0.8


@dataclass
class _M:
    request_count: int = 1
    errors: list = None


class FakeJev:
    """JEV FAKE (NÃO é o JEV): relevância = sigmoide(14·(sobreposição lexical − 0,2)); ponto médio 0,2 escolhido olhando a
    distribuição lexical destes mesmos dados (otimista). Determinístico, sem rede."""
    cfg = _Cfg()

    def __init__(self, down: bool = False):
        self.down, self.calls, self.requests = down, 0, 0

    def evaluate(self, query, candidates):
        if self.down:
            raise RuntimeError("JEV fake fora do ar")
        self.requests += 1
        self.calls += len(candidates)
        for c in candidates:
            c.relevance = 1 / (1 + math.exp(-14 * (lexical(query, c.snippet) - 0.2)))
            c.injection = None
        return candidates, _M(request_count=1, errors=[])


class _Backend:
    cfg = None

    def status(self):
        return {"effective_mode": "replay", "reason": "REPLAY de docs/bench/anam-042-laya-scores.json", "errors": 0,
                "prompt_version": "laya-rel-v2"}

    def resolve_mode(self):
        return "replay"


class ReplayLayaService:
    """Serve as pontuações gravadas do Laya real, por candidate_id. Mesma interface usada pelo provider."""

    def __init__(self, table: dict[str, tuple[float, float]]):
        self.table, self.backend, self.cfg = table, _Backend(), None
        self.calls = 0

    def score(self, query, candidates):
        from app.services.laya_decider import LayaMetrics
        self.calls += len(candidates)
        out = []
        for c in candidates:
            p, conf = self.table[c.candidate_id]
            out.append(LayaAnswer(p_yes=p, p_raw=p, confidence=conf, model="multilingual"))
        return out, LayaMetrics(mode="replay", candidates=len(candidates))

    def injection_gate(self, c):
        return False, ""


# ---------------------------------------------------------------------------------- run
CONFIGS = [
    ("JEV-only (padrão)", dict(provider="jev")),
    ("Laya-only", dict(provider="laya")),
    ("Laya→JEV", dict(provider="hybrid", strategy="laya_then_jev")),
    ("JEV→Laya", dict(provider="hybrid", strategy="jev_then_laya")),
    ("ensemble", dict(provider="hybrid", strategy="ensemble")),
    ("adaptive", dict(provider="adaptive")),
]


def load():
    ds = json.loads(DATA.read_text(encoding="utf-8"))["relevance"]
    sc = json.loads(SCORES.read_text(encoding="utf-8"))["arms"]["multilingual_only"]
    table = {r["id"]: (r["p_raw"], r["conf"]) for r in sc["relevance"]}
    return ds, table, float(sc["batch_per_item_ms"])


def run_config(name, kw, ds, table, laya_ms_per_item, adaptive_min_conf=None):
    cfg = load_config({})
    cfg.cache_size, cfg.history_persist = 0, False
    cfg.provider = kw["provider"]
    cfg.strategy = kw.get("strategy", cfg.strategy)
    if adaptive_min_conf is not None:
        cfg.thresholds["adaptive"] = Thresholds(cfg.thresholds["adaptive"].keep, cfg.thresholds["adaptive"].review,
                                                adaptive_min_conf)
    jev, laya = FakeJev(), ReplayLayaService(table)
    eng = DecisionEngine(cfg, jev=jev, laya_service=laya, history=DecisionHistory(10000, None, False))
    groups: dict[str, list[dict]] = {}
    for it in ds:
        groups.setdefault(it["query"], []).append(it)
    y, pred, pairs, wall, laya_est, per_req_jev_items = [], [], [], [], [], []
    fallbacks = 0
    for q, rows in groups.items():
        before_l = laya.calls
        res = eng.decide(DecisionRequest(q, [Item(r["id"], r["snippet"], "synthetic") for r in rows]))
        wall.append(res.latency_ms)
        laya_est.append((laya.calls - before_l) * laya_ms_per_item)
        per_req_jev_items.append(res.jev_items)
        fallbacks += res.fallback_count
        for r, d in zip(rows, res.items):
            y.append(r["label"])
            pred.append(int(d.survives("keep")))
            o = d.others
            if "laya" in o and "jev" in o:
                pairs.append((o["laya"]["decision"], o["jev"]["decision"]))
    n_req = len(groups)
    jev_items, jev_reqs = jev.calls, jev.requests
    m = prf(y, pred)
    return {
        "name": name, "requests": n_req, "items": len(ds), **{k: m[k] for k in ("precision", "recall", "f1", "tp", "fp", "fn")},
        "jev_items": jev_items, "jev_requests": jev_reqs, "jev_calls_avoided": len(ds) - jev_items,
        "jev_avoided_pct": round(100 * (len(ds) - jev_items) / len(ds), 1),
        "jev_tokens_est": estimate_jev_tokens(jev_reqs, jev_items), "laya_items": laya.calls,
        "laya_ms_total_est": round(laya.calls * laya_ms_per_item, 1),
        "laya_ms_p50_est": round(percentile(laya_est, 0.5), 1), "laya_ms_p95_est": round(percentile(laya_est, 0.95), 1),
        "engine_wall_ms_p50": round(percentile(wall, 0.5), 3), "engine_wall_ms_p95": round(percentile(wall, 0.95), 3),
        "fallbacks": fallbacks, "pairs": pairs,
    }


def fault_checks(ds, table):
    """Fallback por tipo de operação, medido com falhas injetadas (provider derrubado)."""
    rows = ds[:3]
    out = {}
    for op in ("retrieval", "memory", "security"):
        cfg = load_config({})
        cfg.cache_size, cfg.history_persist = 0, False
        eng = DecisionEngine(cfg, jev=FakeJev(down=True), laya_service=None, history=DecisionHistory(100, None, False))
        res = eng.decide(DecisionRequest("q", [Item(r["id"], r["snippet"]) for r in rows], op=op), provider="jev")
        out[op] = {"decisions": sorted({d.decision for d in res.items}), "fallback_action": res.items[0].fallback_action,
                   "all_flagged": all(d.fallback for d in res.items), "dropped_silently": 0}
    return out


def main() -> int:
    ds, table, laya_ms = load()
    y = [r["label"] for r in ds]
    lex = [lexical(r["query"], r["snippet"]) for r in ds]
    laya_scores = [table[r["id"]][0] for r in ds]
    results = [run_config(n, kw, ds, table, laya_ms) for n, kw in CONFIGS]
    sweep = []
    for mc in (0.01, 0.02, 0.05, 0.10, 0.20):
        r = run_config(f"adaptive min_conf={mc}", dict(provider="adaptive"), ds, table, laya_ms, mc)
        sweep.append({k: r[k] for k in ("name", "precision", "recall", "f1", "jev_items", "jev_avoided_pct")})
    # sem filtro (tudo passa) como referência
    nofilter = prf(y, [1] * len(y))
    hy = next(r for r in results if r["name"] == "Laya→JEV")
    div = divergence(hy["pairs"] or [], None)
    # divergência Laya×JEV em TODOS os itens (ensemble avalia os dois em tudo)
    ens = next(r for r in results if r["name"] == "ensemble")
    div_all = divergence(ens["pairs"], [y[i] for i in range(len(y))] if len(ens["pairs"]) == len(y) else None)
    for r in results:
        r.pop("pairs")
    payload = {
        "dataset": {"items": len(ds), "positives": sum(y), "queries": results[0]["requests"],
                    "source": "benchmark/laya_labeled.json (corpus SINTÉTICO; sem vault real)"},
        "labels": {"jev": "FAKE (proxy lexical) — JEV real: não medido", "laya_probs": "REPLAY de ANAM-042 (MEASURED lá)",
                   "laya_latency": "ESTIMATED (227,6 ms/cand. em lote, CPU, execução ANAM-042)",
                   "jev_tokens": "ESTIMATED (340·req + 209·perguntas)", "jev_usd": "UNKNOWN"},
        "reference": {"no_filter": nofilter, "auc_laya": round(auc(laya_scores, y), 3), "auc_lexical": round(auc(lex, y), 3)},
        "results": results, "adaptive_sweep": sweep, "divergence_laya_vs_fakejev": div_all,
        "fault_injection": fault_checks(ds, table),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_MD.write_text(render(payload), encoding="utf-8")
    print(render(payload))
    return 0


def render(p: dict) -> str:
    d, ref = p["dataset"], p["reference"]
    L = ["# Decision Engine — benchmark (ANAM-043)", "",
         "> **JEV real: não medido.** O JEV (TypeSafe) não está acessível e o Colibrì local não estava rodando. As linhas com JEV usam "
         "um **JEV FAKE** (proxy lexical, `scripts/bench_decision.py::FakeJev`): contam chamadas e exercitam o código, mas P/R/F1 "
         "dessas linhas descrevem o proxy, **não o JEV**. Laya = replay das probabilidades reais gravadas em ANAM-042.", "",
         "Rótulos: **MEASURED** (medido aqui/replay de medição), **ESTIMATED** (modelo/extrapolação), **UNKNOWN** (não medido).", "",
         f"Dados: {d['items']} pares consulta×trecho ({d['positives']} positivos) em {d['queries']} consultas — {d['source']}. "
         "Uma requisição = uma consulta com seus candidatos. Cache desligado. Limiares = padrões (não ajustados nestes dados).", "",
         "## Referências", "",
         f"- AUC de relevância: Laya **{ref['auc_laya']}** vs sobreposição lexical **{ref['auc_lexical']}** (MEASURED; coerente com ANAM-042).",
         f"- Sem filtro (tudo passa): P={ref['no_filter']['precision']} R={ref['no_filter']['recall']} F1={ref['no_filter']['f1']}.", "",
         "## Resultado por estratégia", "",
         "| estratégia | P | R | F1 | itens ao JEV | chamadas JEV evitadas | tokens JEV (ESTIMATED) | req. JEV | itens Laya | Laya ms total (ESTIMATED) | Laya p50/p95 por req. ms (ESTIMATED) | engine p50/p95 ms (MEASURED, replay) | fallbacks |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in p["results"]:
        L.append(f"| {r['name']} | {r['precision']} | {r['recall']} | {r['f1']} | {r['jev_items']} | {r['jev_calls_avoided']} "
                 f"({r['jev_avoided_pct']}%) | {r['jev_tokens_est']} | {r['jev_requests']} | {r['laya_items']} | {r['laya_ms_total_est']} | "
                 f"{r['laya_ms_p50_est']}/{r['laya_ms_p95_est']} | {r['engine_wall_ms_p50']}/{r['engine_wall_ms_p95']} | {r['fallbacks']} |")
    L += ["", "Custo total: tokens JEV (ESTIMATED) + tempo de CPU local do Laya (ESTIMATED); **USD do JEV real = UNKNOWN**. "
          "Latência do JEV real = **UNKNOWN** (só o tempo do Laya e o overhead do engine foram quantificados). "
          "\"Chamadas JEV evitadas\" = itens que um JEV-only enviaria e a estratégia não enviou (contagem exata, MEASURED).", "",
          "## Adaptive: varredura de `min_confidence` (exploratória)", "",
          "| config | P | R | F1 | itens ao JEV | JEV evitado |", "|---|---|---|---|---|---|"]
    for s in p["adaptive_sweep"]:
        L.append(f"| {s['name']} | {s['precision']} | {s['recall']} | {s['f1']} | {s['jev_items']} | {s['jev_avoided_pct']}% |")
    dv = p["divergence_laya_vs_fakejev"]
    L += ["", "## Divergência Laya × JEV-FAKE (ensemble avalia os dois em todos os itens)", "",
          f"- agreement_rate (decisão exata): **{dv['agreement_rate']['value']}** ({dv['agreement_rate']['label']})",
          f"- survival_agreement_rate (passa/não passa): **{dv['survival_agreement_rate']['value']}**",
          f"- Cohen κ: **{dv['cohen_kappa']['value']}**; Laya passa/JEV-fake barra: {dv['laya_keep_jev_drop']}; Laya barra/JEV-fake passa: {dv['laya_drop_jev_keep']}"]
    if "vs_labels" in dv:
        v = dv["vs_labels"]
        L.append(f"- Contra rótulos: Laya P/R/F1 = {v['laya']['precision']}/{v['laya']['recall']}/{v['laya']['f1']}; "
                 f"JEV-fake = {v['jev']['precision']}/{v['jev']['recall']}/{v['jev']['f1']}; Laya certa e fake errado: {v['laya_right_jev_wrong']}; "
                 f"fake certo e Laya errada: {v['jev_right_laya_wrong']}.")
    L.append("- A divergência com o JEV REAL é **UNKNOWN**: este número compara Laya com um proxy lexical.")
    L += ["", "## Fallback por tipo de operação (falha injetada: JEV fake fora do ar, Laya ausente)", "",
          "| operação | decisões | ação de fallback | todos sinalizados | descartados em silêncio |", "|---|---|---|---|---|"]
    for op, f in p["fault_injection"].items():
        L.append(f"| {op} | {', '.join(f['decisions'])} | {f['fallback_action']} | {f['all_flagged']} | {f['dropped_silently']} |")
    L += ["", "## Leitura (guiada pelos dados)", "",
          "- Neste corpus a Laya **não supera** o baseline lexical (AUC acima); logo nenhum arranjo com Laya é recomendado para ficar "
          "à frente do padrão. **JEV-only / `graphify_jev_opt` permanece o padrão.**",
          "- A economia de chamadas JEV das estratégias Laya-primeiro é real e contada, mas vem com o custo de qualidade da Laya "
          "(veja recall/F1 das linhas). `JEV→Laya` e `ensemble` gastam o mesmo JEV que o JEV-only: só podem ganhar qualidade, não custo.",
          "- Presets FAST/BALANCED/QUALITY são só configuração, **experimentais** e não validados com JEV real.",
          "- Reproduzir: `python scripts/bench_decision.py` (determinístico; sem rede, sem torch, sem vault)."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
