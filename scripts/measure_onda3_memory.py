"""Onda 3 (ANA-145..163) measurements -> docs/reports/ONDA3_MEMORIA.{md,json}. Offline, deterministic, zero tokens.

    python scripts/measure_onda3_memory.py            # writes the report
    python scripts/measure_onda3_memory.py --check    # exit 1 if a SUCCESS_METRIC regressed
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def measure() -> dict:
    from app.benchmark import golden
    from app.benchmark.memory_eval import (
        budget_curve, contradiction_precision, evaluate_conflict_detector, temporal_arms, temporal_corpus,
    )
    from app.gateway.memory_gateway import MemoryGateway
    from app.services.obsidian import ObsidianVault
    from app.services.provenance import ProvenanceIndex, provenance_tokens
    from config.benchmark import BenchmarkConfig
    from config.retrieval import RetrievalConfig

    res: dict = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        td = Path(td)
        res["ANA-154"] = {s: evaluate_conflict_detector(s) for s in ("train", "val")}
        res["ANA-162"] = contradiction_precision(td / "c")
        root = td / "tv"
        qs = temporal_corpus(root, 8)
        gw = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=root, data_dir=td / "d1"),
                           bench_cfg=BenchmarkConfig(db_path=str(td / "b1.db"), profile="benchmark", benchmark_mode=False))
        gw.warm()
        res["ANA-155"] = temporal_arms(gw, qs)
        synthetic = golden.ROOT / "data" / "synthetic_vault"
        gw2 = MemoryGateway(retrieval_cfg=RetrievalConfig(vault_path=synthetic, data_dir=td / "d2"),
                            bench_cfg=BenchmarkConfig(db_path=str(td / "b2.db"), profile="benchmark", benchmark_mode=False))
        gw2.warm()
        items = [i for i in golden.load(split="val") if i.get("answerable")][:30]
        res["ANA-151"] = budget_curve(gw2, items, [300, 900, 3000])
        idx = ProvenanceIndex(ObsidianVault(synthetic))
        files = sorted({f for it in items for f in (it.get("expected_sources") or [])})[:40]
        full = provenance_tokens([idx.line(f) for f in files])
        compact = provenance_tokens([idx.compact_line(f, i + 1) for i, f in enumerate(files)])
        res["ANA-161"] = {"sources": len(files), "tokens_full": full, "tokens_compact": compact,
                          "saving_pct": round(100 * (1 - compact / full), 1) if full else None}
    return res


def verdicts(r: dict) -> dict:
    v = {}
    val = r["ANA-154"]["val"]["classes"]
    v["ANA-154 precisão/recall val = 1.0"] = all(val[c]["precision"] == 1.0 and val[c]["recall"] == 1.0 for c in val)
    v["ANA-155 versão antiga no topo cai (A→C)"] = r["ANA-155"]["C_demote"]["stale_on_top"] < r["ANA-155"]["A_off"]["stale_on_top"]
    v["ANA-155 versão atual no contexto = 100% (C)"] = r["ANA-155"]["C_demote"]["current_in_context"] == 1.0
    tk = [b["mean_context_tokens"] for b in r["ANA-151"]]
    v["ANA-151 tokens crescem com o orçamento e respeitam o teto"] = (
        tk == sorted(tk) and all(b["mean_context_tokens"] <= b["budget"] * 1.05 for b in r["ANA-151"]))
    v["ANA-161 modo compacto gasta menos que o completo"] = (r["ANA-161"]["tokens_compact"] or 0) < (r["ANA-161"]["tokens_full"] or 1)
    v["ANA-162 precision@N ≥ 0.7"] = (r["ANA-162"]["precision_at_n"] or 0) >= 0.7
    return v


def render_md(r: dict, v: dict) -> str:
    L = ["# Onda 3 — Memória + provenance: medições (ANA-145..163)", "",
         "Geradas por `scripts/measure_onda3_memory.py`. Offline, determinístico, zero tokens. Dados SINTÉTICOS:",
         "isto valida regras e regressões, não qualidade em dados reais (o vault real tem 0 notas supersedidas).", "",
         "## Verificações", ""]
    L += [f"- [{'x' if ok else ' '}] {name}" for name, ok in v.items()]
    L += ["", "## ANA-154 — detector de duplicata/contradição (par nota nova × antiga)", "",
          "| split | n | classe | precisão | recall |", "|---|---|---|---|---|"]
    for s, d in r["ANA-154"].items():
        for c, m in d["classes"].items():
            L.append(f"| {s} | {d['n']} | {c} | {m['precision']} | {m['recall']} |")
    p = r["ANA-162"]
    L += ["", "## ANA-162 — contradição offline (candidatos p/ revisão humana)", "",
          f"pares rotulados: {p['n_pairs']} · sinalizados: {p['flagged']} · TP {p['tp']} / FP {p['fp']} / FN {p['fn']} · "
          f"precision@N = {p['precision_at_n']} (N={p['n']}) · recall = {p['recall']}", "",
          "## ANA-155 — benefício temporal (sintético)", "", "| braço | atual no contexto | antiga no topo | antiga entregue |", "|---|---|---|---|"]
    for a, m in r["ANA-155"].items():
        L.append(f"| {a} | {m['current_in_context']} | {m['stale_on_top']} | {m['stale_delivered']} |")
    L += ["", "## ANA-151 — recall × orçamento de contexto (golden val, BM25 baseline)", "",
          "| orçamento | n | recall | fact_in_context | tokens médios |", "|---|---|---|---|---|"]
    for b in r["ANA-151"]:
        L.append(f"| {b['budget']} | {b['n']} | {b['recall']} | {b['fact_in_context']} | {b['mean_context_tokens']} |")
    c = r["ANA-161"]
    L += ["", "## ANA-161 — proveniência compacta", "",
          f"{c['sources']} fontes: completo = {c['tokens_full']} tokens, compacto = {c['tokens_compact']} tokens "
          f"(−{c['saving_pct']}%). Padrão continua `full` (opt-in por `MG_OPT_PROVENANCE_MODE=compact`).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    r = measure()
    v = verdicts(r)
    if a.check:
        bad = [k for k, ok in v.items() if not ok]
        print("OK" if not bad else "FAIL: " + "; ".join(bad))
        return 1 if bad else 0
    out = ROOT / "docs" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ONDA3_MEMORIA.json").write_text(json.dumps({"results": r, "verdicts": v}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "ONDA3_MEMORIA.md").write_text(render_md(r, v), encoding="utf-8")
    print(render_md(r, v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
