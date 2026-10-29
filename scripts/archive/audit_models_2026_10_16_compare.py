"""Fase 4: matriz comparativa a partir do JSON bruto (sem rodar modelos).

    .venv/Scripts/python.exe scripts/archive/audit_models_2026_10_16_compare.py

Colunas: lexical (prefilter), Laya (inproc multilingual), Qwen3.8 via /v1/systemone (Colibrì), cascata Laya->Qwen nos itens
incertos (faixa REVIEW da Laya: drop<=p<keep). Intervalos: Wilson 95% para precisão/recall. Tudo MEASURED sobre n=20
(relevância) e n=20 (privacidade); amostras pequenas: diferenças < ~0,3 não são significativas.
"""
import json
import math
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "reports-out" / "auditoria-modelos-2026-10-16.json"
LABELED = ROOT / "benchmark" / "laya_labeled.json"
_TOK = re.compile(r"[a-z0-9][a-z0-9._-]{3,}")


def lexical(q, note):   # idêntico a scripts/bench_laya.py
    qs, ns = set(_TOK.findall(q.lower())), set(_TOK.findall(note.lower()))
    return len(qs & ns) / max(1, len(qs))


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0, c - h), 2), round(min(1, c + h), 2))


def prf(pred, lab):
    tp = sum(1 for p, l in zip(pred, lab) if p and l)
    fp = sum(1 for p, l in zip(pred, lab) if p and not l)
    fn = sum(1 for p, l in zip(pred, lab) if not p and l)
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    F = 2 * P * R / (P + R) if P + R else 0.0
    return {"P": round(P, 3), "R": round(R, 3), "F1": round(F, 3), "tp": tp, "fp": fp, "fn": fn,
            "P_ci95": wilson(tp, tp + fp), "R_ci95": wilson(tp, tp + fn)}


def pct(v, q):
    v = sorted(v)
    k = (len(v) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def main():
    d = json.loads(RAW.read_text(encoding="utf-8"))
    rel = {r["id"]: r for r in json.loads(LABELED.read_text(encoding="utf-8"))["relevance"]}
    laya = {i["id"]: i for i in d["laya_direct"]["relevancia_20"]["itens"]}
    qw = {i["id"]: i for i in (d.get("qwen", {}).get("relevancia_20") or [])}
    ids = [i for i in laya if i in qw] if qw else list(laya)
    lab = [rel[i]["label"] for i in ids]
    out = {"n_relevancia": len(ids), "label": "MEASURED", "colunas": {}}
    lex = [lexical(rel[i]["query"], rel[i]["snippet"]) for i in ids]
    out["colunas"]["lexical>=0.5"] = {**prf([s >= 0.5 for s in lex], lab), "lat_ms": "~0 (não medido: cálculo trivial)", "ram_mb": "UNKNOWN",
                                       "vram_mb": 0, "custo_usd": 0}
    kp = d["laya_direct"]["keep_threshold"]
    dp = d["laya_direct"]["drop_threshold"]
    lp = [laya[i]["p_yes"] for i in ids]
    out["colunas"]["laya_keep>=0.25"] = {**prf([p >= kp for p in lp], lab), "p50_ms": d["laya_direct"]["frio_quente"]["seguintes_p50_ms"],
                                          "p95_ms": d["laya_direct"]["frio_quente"]["seguintes_p95_ms"],
                                          "ram_mb": d["laya_direct"]["ram_processo_mb_pos_carga"]["valor"], "vram_mb": 0, "custo_usd": 0}
    if qw:
        qp = [qw[i]["p_yes"] for i in ids]
        ql = [qw[i]["ms"] for i in ids]
        eng = d["qwen"].get("engine_fim") or d["qwen"].get("engine_inicio") or {}
        for th in (0.25, 0.5):
            out["colunas"][f"qwen38_systemone>={th}"] = {**prf([p >= th for p in qp], lab), "p50_ms": pct(ql, 50), "p95_ms": pct(ql, 95),
                                                         "ram_mb": eng.get("rss_mb"), "vram_mb": "UNKNOWN (NVML falha)", "custo_usd": 0}
        casc, calls = [], 0
        for i, p in zip(ids, lp):
            if dp <= p < kp:      # incerto = faixa REVIEW da Laya
                casc.append(qw[i]["p_yes"] >= 0.5)
                calls += 1
            else:
                casc.append(p >= kp)
        out["colunas"]["cascata_laya->qwen(REVIEW)"] = {**prf(casc, lab), "chamadas_qwen": calls, "chamadas_qwen_evitadas": len(ids) - calls,
                                                         "lat_total_est_ms": "ESTIMATED: laya p50*N + qwen p50*chamadas"}
        out["auc"] = {"lexical": _auc(lex, lab), "laya": _auc(lp, lab), "qwen": _auc(qp, lab)}
    else:
        out["auc"] = {"lexical": _auc(lex, lab), "laya": _auc(lp, lab)}
    ol = d.get("ollama")
    if ol:
        om = {i["id"]: i for i in ol["relevancia_20"]}
        oi = [i for i in ids if i in om]
        olab = [rel[i]["label"] for i in oi]
        lat = [om[i]["ms"] for i in oi]
        out["colunas"]["qwen3.5-9b_ollama(letra A)"] = {**prf([om[i]["pred"] for i in oi], olab), "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95),
                                                        "ram_mb": "UNKNOWN", "vram_mb": "UNKNOWN (ver ollama ps)", "custo_usd": 0,
                                                        "obs": "sem probabilidades (só a letra)"}
        casc2, calls2 = [], 0
        for i, p in zip(ids, lp):
            if dp <= p < kp and i in om:
                casc2.append(om[i]["pred"]); calls2 += 1
            else:
                casc2.append(p >= kp)
        out["colunas"]["cascata_laya->qwen3.5-9b(REVIEW)"] = {**prf(casc2, lab), "chamadas_modelo_grande": calls2, "evitadas": len(ids) - calls2}
        po = {i["id"]: i for i in ol["privacidade_10"]}
        pj = list(po)
        out["privacidade_ollama"] = {"n": len(pj), **prf([po[i]["pred"] for i in pj], [po[i]["truth"] for i in pj])}
    # privacidade
    lpriv = {i["id"]: i for i in d["laya_direct"]["privacidade_20"]["itens"]}
    qpriv = {i["id"]: i for i in ((d.get("qwen_priv", {}).get("privacidade_20")) or d.get("qwen", {}).get("privacidade_20") or [])}
    pid = [i for i in lpriv if i in qpriv] if qpriv else []
    if pid:
        tl = [lpriv[i]["truth"] for i in pid]
        out["privacidade"] = {"n": len(pid), "laya": prf([lpriv[i]["private"] for i in pid], tl),
                              "qwen>=0.5": prf([qpriv[i]["p_yes"] >= 0.5 for i in pid], tl),
                              "qwen>=0.1": prf([qpriv[i]["p_yes"] >= 0.1 for i in pid], tl)}
    d["comparacao"] = out
    RAW.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def _auc(s, lab):
    pos = [x for x, l in zip(s, lab) if l]
    neg = [x for x, l in zip(s, lab) if not l]
    return round(sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg)), 3) if pos and neg else None


if __name__ == "__main__":
    main()
