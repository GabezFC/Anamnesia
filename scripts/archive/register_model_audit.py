"""Registra a auditoria de modelos no histórico do Anamnésia (benchmark.db), com tokens e custo.

    .venv/Scripts/python.exe scripts/archive/register_model_audit.py [--json data/reports-out/auditoria-modelos-2026-10-16.json]
                                                              [--session audit-modelos-2026-10-16] [--db <caminho>] [--dry-run]

Lê o JSON bruto de `scripts/archive/audit_models_2026_10_16.py` e grava UMA run por (modelo/estratégia × tarefa) numa sessão
`kind="model_audit"` (fora de BENCHMARK_KINDS: não polui a métrica ANA-089). Idempotente: run_id determinístico +
INSERT OR REPLACE. Só escreve via SQLite (WAL) — NÃO precisa reiniciar nem parar o servidor em :8000.

Regras de rótulo (nada inventado):
  - tokens: só quando o motor devolveu `usage` / `prompt_eval_count` (Colibrì/Qwen, Ollama). Laya e lexical = não
    generativos → tokens `null` (não medido), nunca 0 inventado. Custo de modelo LOCAL = 0.0 USD (marginal, medido).
  - JEV (TypeSafe pago): preço não verificado → `cost_usd = null` (UNKNOWN). A rodada JEV real acidental fica marcada.
  - Sem texto de query/candidato: `query` guarda só o nome da tarefa; ids são hashes/ids sintéticos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.database.db import Database  # noqa: E402
from config.paths import benchmark_db_path  # noqa: E402

KIND = "model_audit"


def _pct(vals, q):
    v = sorted(x for x in vals if x is not None)
    return round(v[min(len(v) - 1, int(q * len(v)))], 1) if v else None


def build_rows(d: dict) -> list[dict]:
    rows: list[dict] = []

    def add(pipeline, provider, model, task, *, mode="local", metrics=None, tokens=None, cost: float | None = 0.0,
            cost_origin="measured", jev_model=None, note=""):
        m = dict(metrics or {})
        t = tokens or {}
        m.update({
            "audit_task": task, "audit_note": note, "label": m.get("label", "MEASURED"),
            "prompt_tokens": t.get("prompt"), "completion_tokens": t.get("completion"),
            "tokens_origin": t.get("origin", "unavailable"),
            "cost_usd_value": cost, "cost_origin_detail": cost_origin,
            "local_marginal_cost": cost == 0.0 and cost_origin == "measured",
        })
        if t.get("prompt") is not None or t.get("completion") is not None:
            m["total_tokens_spent"] = (t.get("prompt") or 0) + (t.get("completion") or 0)
        rid = hashlib.sha256(f"{pipeline}|{model}|{task}".encode()).hexdigest()[:20]
        rows.append({"run_id": f"audit-{rid}", "question_id": task, "query": f"[audit] {task}", "pipeline": pipeline,
                     "provider": provider, "model": model, "mode": mode, "metrics_json": m,
                     "cost_origin": cost_origin if cost_origin in ("measured", "estimated", "unavailable") else "unavailable",
                     "jev_model": jev_model})

    # ---- Laya (inproc multilingual) — não generativa: sem tokens, custo local 0
    L = d.get("laya_direct", {})
    fq = L.get("frio_quente", {})
    lat = {"total_latency_ms": fq.get("seguintes_media_ms"), "p50_ms": fq.get("seguintes_p50_ms"),
           "p95_ms": fq.get("seguintes_p95_ms"), "cold_first_call_ms": fq.get("primeira_chamada_ms")}
    for key in ("relevancia_192", "relevancia_20", "privacidade_20", "injecao_20"):
        x = L.get(key)
        if not x:
            continue
        x = x.get("laya", x)
        add("audit:laya", "laya", "laya-multilingual", key,
            metrics={**lat, **{k: x.get(k) for k in ("n", "auc", "precision", "recall", "f1", "tp", "fp", "fn")},
                     "ram_mb": d.get("comparacao", {}).get("colunas", {}).get("laya_keep>=0.25", {}).get("ram_mb")},
            note="decisor não generativo; tokens não contabilizados pelo motor")
    cal = L.get("calibracao_192")
    if cal:
        add("audit:laya", "laya", "laya-multilingual", "calibracao_192",
            metrics={"n": cal["n"], "ece_confidence_vs_acerto": cal["ece_confidence_vs_acerto"],
                     "ece_pA_vs_rotulo": cal["ece_pA_vs_rotulo"]}, note="superconfiança: ECE(confidence) alto")

    # ---- matriz comparativa (n=20): lexical, laya, qwen3.8 (Colibrì), qwen3.5-9b (Ollama), cascatas
    cols = d.get("comparacao", {}).get("colunas", {})
    qrel = d.get("qwen", {}).get("relevancia_20", [])
    qin = sum(i.get("in_tokens") or 0 for i in qrel)
    gen = d.get("qwen", {}).get("geracao", {})
    gen_runs = gen.get("runs", []) + d.get("qwen", {}).get("prefix_cache", {}).get("chamadas", [])
    gp = sum((r.get("usage") or {}).get("prompt_tokens") or 0 for r in gen_runs)
    gc = sum((r.get("usage") or {}).get("completion_tokens") or 0 for r in gen_runs)
    ol = d.get("ollama", {})
    orel, opriv = ol.get("relevancia_20", []), ol.get("privacidade_10", [])

    def otok(items):
        p = sum(((i.get("tokens") or {}).get("prompt") or 0) for i in items)
        c = sum(((i.get("tokens") or {}).get("completion") or 0) for i in items)
        has = any((i.get("tokens") or {}).get("prompt") is not None for i in items)
        return {"prompt": p if has else None, "completion": c if has else None, "origin": "measured" if has else "unavailable"}

    def prf(c):
        return {k: c.get(k) for k in ("P", "R", "F1", "tp", "fp", "fn", "P_ci95", "R_ci95", "p50_ms", "p95_ms", "ram_mb", "vram_mb")}

    if "lexical>=0.5" in cols:
        add("audit:lexical", "local", "prefilter-lexical", "relevancia_20", metrics={**prf(cols["lexical>=0.5"]), "n": 20,
            "auc": d["comparacao"]["auc"].get("lexical")}, note="baseline sem modelo; tokens n/a")
    for name, key, task in (("qwen3.8-colibri", "qwen38_systemone>=0.25", "relevancia_20@0.25"),
                            ("qwen3.8-colibri", "qwen38_systemone>=0.5", "relevancia_20@0.5")):
        if key in cols:
            add("audit:qwen38", "colibri", "qwen3.8-systemone", task,
                metrics={**prf(cols[key]), "n": 20, "total_latency_ms": cols[key].get("p50_ms"),
                         "auc": d["comparacao"]["auc"].get("qwen")},
                tokens={"prompt": qin, "completion": None, "origin": "estimated"},
                note="tokens de entrada = soma de in_tokens por item (contagem do motor); saída não reportada")
    if gen_runs:
        add("audit:qwen38", "colibri", "qwen3.8-systemone", "geracao+prefix_cache",
            metrics={"n": len(gen_runs), "total_latency_ms": round(statistics.mean(r["total_s"] for r in gen_runs) * 1000, 1),
                     "ttft_s_mean": round(statistics.mean(r["ttft_s"] for r in gen_runs), 2),
                     "decode_tok_s_mean": round(statistics.mean(r["decode_tok_s"] for r in gen_runs), 3)},
            tokens={"prompt": gp, "completion": gc, "origin": "measured"}, note="usage devolvido pela API do Colibrì")
    qp = d.get("qwen_priv", {}).get("privacidade_20", [])
    pq = d.get("comparacao", {}).get("privacidade", {})
    if qp:
        add("audit:qwen38", "colibri", "qwen3.8-systemone", "privacidade_10",
            metrics={"n": len(qp), "total_latency_ms": round(statistics.mean(i["ms"] for i in qp), 1),
                     "p50_ms": _pct([i["ms"] for i in qp], .5), "p95_ms": _pct([i["ms"] for i in qp], .95),
                     "qwen>=0.5": pq.get("qwen>=0.5"), "qwen>=0.1": pq.get("qwen>=0.1")},
            note="uso de tokens não capturado nesta etapa")
    if orel:
        c = cols.get("qwen3.5-9b_ollama(letra A)", {})
        add("audit:ollama_qwen35_9b", "ollama", "qwen3.5:9b", "relevancia_20",
            metrics={**prf(c), "n": len(orel), "total_latency_ms": round(statistics.mean(i["ms"] for i in orel), 1)},
            tokens=otok(orel), note="prompt_eval_count/eval_count do Ollama; CPU")
    if opriv:
        add("audit:ollama_qwen35_9b", "ollama", "qwen3.5:9b", "privacidade_10",
            metrics={**d.get("comparacao", {}).get("privacidade_ollama", {}), "n": len(opriv),
                     "total_latency_ms": round(statistics.mean(i["ms"] for i in opriv), 1)},
            tokens=otok(opriv), note="prompt_eval_count/eval_count do Ollama; CPU")
    for key, pipe, model in (("cascata_laya->qwen(REVIEW)", "audit:cascata_laya_qwen38", "laya+qwen3.8"),
                             ("cascata_laya->qwen3.5-9b(REVIEW)", "audit:cascata_laya_qwen35", "laya+qwen3.5:9b")):
        if key in cols:
            add(pipe, "cascade", model, "relevancia_20", metrics={**prf(cols[key]), "n": 20,
                "big_model_calls": cols[key].get("chamadas_qwen", cols[key].get("chamadas_modelo_grande")),
                "big_model_calls_avoided": cols[key].get("chamadas_qwen_evitadas", cols[key].get("evitadas")),
                "label": "MEASURED(P/R) + ESTIMATED(latência)"}, note="itens REVIEW da Laya escalam ao modelo maior")

    # ---- Decision Engine: 6 estratégias × 30 itens (duas rodadas: com JEV real acidental e a segunda)
    for tag, key, jev_real in (("rodada1_jev_real_acidental", "api_8010_PRIMEIRA_RODADA_JEV_REAL_ACIDENTAL", True),
                               ("rodada2", "api_8010", False)):
        for e in d.get(key, {}).get("estrategias_30", []):
            name = e["provider"] + (":" + e["strategy"] if e.get("strategy") else "")
            calls = e.get("calls", {})
            uses_jev = calls.get("jev", 0) > 0
            pipe = f"audit:decision_{name.replace(':', '_')}" + ("_jev" if uses_jev and "jev" not in name else "")
            add(pipe, "decision-engine", name, f"estrategias_30/{tag}",
                metrics={"n": 30, "total_latency_ms": e["ms"], "decisions": e["decisoes"], "calls": calls,
                         "jev_calls": calls.get("jev", 0), "laya_calls": calls.get("laya", 0),
                         "jev_calls_avoided": (e.get("jev_calls_avoided") or {}).get("value"),
                         "fallbacks": e.get("fallbacks"), "cache_hits": e.get("cache_hits")},
                cost=None if uses_jev else 0.0, cost_origin="unavailable" if uses_jev else "measured",
                jev_model="typesafe(.env)" if uses_jev else None,
                note=("JEV pago chamado de verdade (preço não verificado → custo UNKNOWN; violação do limite US$0)"
                      if (uses_jev and jev_real) else "JEV configurado no .env; custo não verificado" if uses_jev else "100% local"))
    for e in d.get("estrategias_30_metricas", {}).get("linhas", []):
        add("audit:decision_agreement", "decision-engine", e["estrategia"], "concordancia_vs_jev",
            metrics={k: e.get(k) for k in ("keeps", "agreement_vs_jev", "kappa_vs_jev", "laya_only_keep", "jev_only_keep",
                                          "jev_calls", "jev_avoided", "fallbacks")} | {"n": 30},
            note="rótulo vs q0 único é falha de desenho (ver AVISO no JSON); use agreement/kappa")

    # ---- REST/API/fallback/cache do engine
    r = d.get("rest_8010", {}).get("decision_individual")
    if r:
        add("audit:decision_rest", "decision-engine", "POST /api/decision/decision", "latencia_rest",
            metrics={"n": len(r["requests"]), "total_latency_ms": r["p50_ms"], "p50_ms": r["p50_ms"], "p95_ms": r["p95_ms"],
                     "batch_ms": d["rest_8010"].get("batch", {}).get("ms")}, note="loopback; sem texto na resposta")
    ca = d.get("api_8010", {}).get("cache")
    if ca:
        add("audit:decision_cache", "decision-engine", "cache LRU", "frio_vs_hit",
            metrics={"total_latency_ms": ca["frio_ms"], "cold_ms": ca["frio_ms"], "hit_ms": ca["hit_ms"], "hits": ca["hits_2a"]})
    for key in ("fallback_jev_down", "fallback_ambos_down"):
        f = d.get(key)
        if f:
            add("audit:decision_fallback", "decision-engine", key, f.get("tag", key),
                metrics={"casos": [{k: c.get(k) for k in ("op", "provider", "ms", "decisoes", "acao")} for c in f["casos"]],
                         "total_latency_ms": round(statistics.mean(c["ms"] for c in f["casos"]), 1)},
                note="fallback explícito por operação (retrieval=allow, memory=review, security=quarantine)")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(ROOT / "data" / "reports-out" / "auditoria-modelos-2026-10-16.json"))
    ap.add_argument("--session", default="audit-modelos-2026-10-16")
    ap.add_argument("--db", default=str(benchmark_db_path()))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    d = json.load(open(a.json, encoding="utf-8"))
    rows = build_rows(d)
    if a.dry_run:
        for r in rows:
            m = r["metrics_json"]
            print(f"{r['pipeline']:34} {r['model']:26} {r['question_id']:34} tok={m.get('total_tokens_spent')} cost={m.get('cost_usd_value')}")
        print(len(rows), "linhas (dry-run)")
        return 0
    db = Database(a.db)
    db.create_session(a.session, KIND, {"source": Path(a.json).name, "script": "scripts/archive/register_model_audit.py",
                                        "labels": "MEASURED/ESTIMATED/UNKNOWN", "cache_enabled": False},
                      notes="Auditoria de modelos 2026-10-16: Laya, Qwen3.8 (Colibrì), Qwen3.5-9B (Ollama), Decision Engine")
    t0 = time.time()
    for i, r in enumerate(rows):
        db.save_run({**r, "session_id": a.session, "created_at": t0 + i * 0.001, "agent": "audit", "repetition": 0,
                     "warmup": 0, "order_index": i, "cache_enabled": 0})
    print(f"{len(rows)} runs gravadas na sessão {a.session} ({a.db})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
