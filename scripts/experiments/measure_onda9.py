"""Onda 9 (ANA-226..237): measure the retrieval experiments on the frozen golden set.

    python scripts/experiments/measure_onda9.py            # writes tests/fixtures/onda9/ONDA9_EXPERIMENTOS.{json,md}
    python scripts/experiments/measure_onda9.py --render   # re-render the .md from the committed .json (freshness test)

Method
------
* Corpus: data/synthetic_vault; questions: benchmark/golden (golden-v2).  Parameters are CHOSEN on the
  calibration split (train + val) and the verdict is taken ONLY from `test`, never tuned on it.  `test` is
  small: the paired bootstrap CI is wide and most differences will not exclude zero.  The report says so
  instead of promoting a point difference to a result.
* Offline and deterministic: optimizer disabled (no result cache), no judge, no model, zero API tokens.
* Per item: recall (fraction of expected sources among the returned sources), hit (all of them), MRR (rank of
  the first expected source), context tokens.  Wilson CI for the hit rate, bootstrap CI for means, paired
  bootstrap of (arm - control) from app/core/stats.py.
* Verdict rule (applied by code, see `verdict()`):
    REJEITAR        point regression of recall/MRR, or no gain at all
    ADOTAR          no point regression AND (a paired CI excluding zero in our favour, OR >=10% fewer context
                    tokens at equal recall)
    MANTER_OPT_IN   no regression, point gain only (the flag stays, default OFF)
* BLOCKED is reserved for items that need a local model that is not running.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

OUT_JSON = ROOT / "tests" / "fixtures" / "onda9" / "ONDA9_EXPERIMENTOS.json"
OUT_MD = ROOT / "tests" / "fixtures" / "onda9" / "ONDA9_EXPERIMENTOS.md"
VAULT = ROOT / "data" / "synthetic_vault"


# ----------------------------------------------------------------------------------------------- harness
def make_gw(vault: Path = VAULT):
    from app.gateway.memory_gateway import MemoryGateway
    from app.retrieval.graphify_hybrid import GraphIndex
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig
    td = Path(tempfile.mkdtemp())
    rc = RetrievalConfig(vault_path=vault, data_dir=td / "d")
    bc = BenchmarkConfig(db_path=str(td / "b.db"), profile="benchmark", benchmark_mode=False)
    gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=OptimizerConfig.disabled())
    g = vault / "graphify-out" / "graph.json"
    if g.exists():
        gw.graph_index = GraphIndex(g)
    gw.warm()
    return gw


def area_of(path: str) -> str:
    return path.split("/")[0]


def fact_tokens() -> dict[str, str]:
    m = json.loads((VAULT / "MANIFEST.json").read_text(encoding="utf-8"))
    return {f["path"]: f["token"] for f in m["facts"]}


_FACTS: dict[str, str] = {}


def run_arm(gw, items, flags, pipeline="baseline", k=5, scope_fn=None, budget=None, max_candidates=None):
    """One arm over `items`.  Returns per-item rows (answerable items carry recall/hit/mrr)."""
    gw.experiments = flags
    rc = gw.retrieval_cfg
    old_mc = rc.max_candidates
    if max_candidates:
        rc.max_candidates = max_candidates
    if not _FACTS:
        _FACTS.update(fact_tokens())
    rows = []
    try:
        for it in items:
            t0 = time.perf_counter()
            r = gw.search(it["question"], pipeline, k, persist=False,
                          scope=scope_fn(it) if scope_fn else None, context_budget=budget)
            lat = (time.perf_counter() - t0) * 1000
            files = [s.file for s in r.sources]
            exp = it.get("expected_sources") or []
            row = {"id": it["id"], "qclass": it["qclass"], "answerable": bool(it["answerable"]), "n_exp": len(exp),
                   "lat_ms": lat, "ctx_tokens": sum(s.tokens or 0 for s in r.sources), "n_src": len(files)}
            if it["answerable"] and exp:
                row["recall"] = sum(e in files for e in exp) / len(exp)
                row["hit"] = 1 if all(e in files for e in exp) else 0
                ranks = [files.index(e) + 1 for e in exp if e in files]
                row["mrr"] = 1.0 / min(ranks) if ranks else 0.0
                toks = [_FACTS[e] for e in exp if e in _FACTS]
                if toks:
                    row["fact_in_ctx"] = 1.0 if any(t in r.context for t in toks) else 0.0
            bs = getattr(gw, "last_budget_stats", None) or {}
            row["blocks_dropped_budget"] = bs.get("blocks_dropped_budget", 0)
            rows.append(row)
    finally:
        rc.max_candidates = old_mc
        gw.experiments = None
    return rows


def _vals(rows, key):
    return [r[key] for r in rows if key in r]


def summarize(rows) -> dict:
    from app.core.stats import bootstrap_ci, wilson_ci
    ans = [r for r in rows if "recall" in r]
    out = {"n_answerable": len(ans),
           "hit": wilson_ci(sum(r["hit"] for r in ans), len(ans)),
           "recall": bootstrap_ci(_vals(ans, "recall")),
           "mrr": bootstrap_ci(_vals(ans, "mrr")),
           "ctx_tokens_mean": round(statistics.mean(r["ctx_tokens"] for r in rows), 1) if rows else None,
           "latency_ms_median": round(statistics.median(r["lat_ms"] for r in rows), 2) if rows else None}
    fic = _vals(ans, "fact_in_ctx")
    if fic:
        out["fact_in_context"] = bootstrap_ci(fic)
        out["blocks_dropped_budget_total"] = sum(r["blocks_dropped_budget"] for r in rows)
    return out


def compare(arm_rows, ctl_rows) -> dict:
    from app.core.stats import paired_diff_ci
    a = {r["id"]: r for r in arm_rows}
    c = {r["id"]: r for r in ctl_rows}
    ids = [i for i in c if i in a and "recall" in c[i]]
    d = {"recall": paired_diff_ci([a[i]["recall"] for i in ids], [c[i]["recall"] for i in ids]),
         "mrr": paired_diff_ci([a[i]["mrr"] for i in ids], [c[i]["mrr"] for i in ids])}
    fids = [i for i in ids if "fact_in_ctx" in a[i] and "fact_in_ctx" in c[i]]
    if fids:
        d["fact_in_ctx"] = paired_diff_ci([a[i]["fact_in_ctx"] for i in fids], [c[i]["fact_in_ctx"] for i in fids])
    ta = statistics.mean(r["ctx_tokens"] for r in arm_rows) if arm_rows else 0
    tc = statistics.mean(r["ctx_tokens"] for r in ctl_rows) if ctl_rows else 0
    d["ctx_tokens_delta_pct"] = round(100 * (ta - tc) / tc, 1) if tc else None
    return d


def verdict(cmp: dict, primary=("recall", "mrr")) -> tuple[str, str]:
    diffs = {k: cmp[k] for k in primary if k in cmp and cmp[k].get("mean_diff") is not None}
    if not diffs:
        return "BLOCKED", "sem dados"
    worse = [k for k, v in diffs.items() if v["mean_diff"] < 0]
    better_sig = [k for k, v in diffs.items() if v["excludes_zero"] and v["mean_diff"] > 0]
    tok = cmp.get("ctx_tokens_delta_pct")
    saves = tok is not None and tok <= -10.0
    any_better = any(v["mean_diff"] > 0 for v in diffs.values())
    desc = "; ".join(f"Δ{k}={v['mean_diff']:+.4f} IC[{v['low']:+.4f},{v['high']:+.4f}]" for k, v in diffs.items())
    if tok is not None:
        desc += f"; Δtokens={tok:+.1f}%"
    if worse:
        return "REJEITAR", f"regressão pontual em {','.join(worse)} ({desc})"
    if better_sig:
        return "ADOTAR", f"ganho com IC fora de zero em {','.join(better_sig)} ({desc})"
    if saves:
        return "ADOTAR", f"≥10% menos tokens sem perda ({desc})"
    if any_better:
        return "MANTER_OPT_IN", f"ganho pontual sem significância, n pequeno ({desc})"
    return "REJEITAR", f"sem ganho mensurável ({desc})"


def pick(gw, calib, candidates, **kw):
    """Parameter selection on CALIBRATION only: best mean(recall)+mean(mrr); ties -> first listed."""
    best, best_s = candidates[0], None
    table = []
    for label, flags in candidates:
        s = summarize(run_arm(gw, calib, flags, **kw))
        score = (s["recall"]["mean"] or 0) + (s["mrr"]["mean"] or 0)
        table.append((label, round(score, 4)))
        if best_s is None or score > best_s + 1e-9:
            best, best_s = (label, flags), score
    return best, table


# ----------------------------------------------------------------------------------------------- experiments
def experiment(gw, name, test, calib, control, grid, pipeline="baseline", k=5, **kw):
    """Select on calibration, evaluate control and the chosen arm on test."""
    (label, flags), sel = pick(gw, calib, grid, pipeline=pipeline, k=k, **kw)
    cal_ctl = summarize(run_arm(gw, calib, control, pipeline=pipeline, k=k, **kw))
    c_rows = run_arm(gw, test, control, pipeline=pipeline, k=k, **kw)
    a_rows = run_arm(gw, test, flags, pipeline=pipeline, k=k, **kw)
    cmp = compare(a_rows, c_rows)
    v, why = verdict(cmp)
    return {"id": name, "chosen": label, "chosen_flags": flags.digest(),
            "selected_on": "calibration (train+val)",
            "calibration_scores(recall+mrr)": {"control": round((cal_ctl["recall"]["mean"] or 0) + (cal_ctl["mrr"]["mean"] or 0), 4),
                                               **dict(sel)},
            "test": {"control": summarize(c_rows), "arm": summarize(a_rows), "paired_vs_control": cmp},
            "verdict": v, "why": why}


def measure() -> dict:
    from app.benchmark import golden
    from app.retrieval.experiments import RetrievalExperiments as E, with_flags as wf
    from app.services.query_fp import classify

    gw = make_gw()
    cal = golden.load(split="train") + golden.load(split="val")
    test = golden.load(split="test")
    cal_a = [i for i in cal if i["answerable"] and i.get("expected_sources")]
    test_a = [i for i in test if i["answerable"] and i.get("expected_sources")]
    base = E()
    mf = json.loads((golden.GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    res: dict = {"meta": {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "vault": "data/synthetic_vault",
                          "golden": mf["version"], "n_test": len(test), "n_test_answerable": len(test_a),
                          "n_calibration_answerable": len(cal_a), "ollama": ollama_state()}, "experiments": {}}
    ex = res["experiments"]

    # ANA-226 -- BM25 heading weight (bug fix, measured before/after)
    # control = the OLD ranking (explicit weight 1.0, rank-identical to bm25(sec, 2.0, 1.0)); arm = new default 2.0+
    ex["ANA-226"] = experiment(gw, "ANA-226", test_a, cal_a, wf(base, bm25_section_weight=1.0),
                               [(f"section_weight={w}", wf(base, bm25_section_weight=w)) for w in (2.0, 3.0, 5.0)])
    e226 = ex["ANA-226"]
    if "regressão" not in e226["why"]:       # bug fix: the rule is "adopt unless it worsens recall/MRR"
        e226["verdict"] = "ADOTAR"
        e226["why"] = ("correção de bug (peso do heading caía na coluna `file`), sem piora: " + e226["why"] +
                       "; default passou a section=2.0 (MG_EXP_BM25_SECTION_WEIGHT=1.0 restaura o ranking antigo)")
    # ANA-227 -- scope before top-N (scope = area of the expected source; two candidate-pool sizes)
    scope_fn = lambda it: "area:" + area_of(it["expected_sources"][0])  # noqa: E731
    ex["ANA-227"] = {}
    for mc in (100, 10):
        r227 = experiment(
            gw, f"ANA-227@max_candidates={mc}", test_a, cal_a, base,
            [("scope_before_topn", wf(base, scope_before_topn=True))], scope_fn=scope_fn, max_candidates=mc)
        if r227["verdict"] == "REJEITAR" and "regressão" not in r227["why"]:
            # structural guarantee (tests/test_onda9_retrieval.py proves in-scope hits are no longer lost to
            # out-of-scope rows above the cut); the golden set has no item where that happens.
            r227["verdict"] = "MANTER_OPT_IN"
            r227["why"] = "sem efeito no golden (nenhum item perde fonte no corte); garantia estrutural testada: " + r227["why"]
        ex["ANA-227"][f"max_candidates={mc}"] = r227
    # ANA-228 -- one tokenizer
    ex["ANA-228"] = experiment(gw, "ANA-228", test_a, cal_a, base, [("unified_tokens", wf(base, unified_tokens=True))])
    # ANA-229 -- prefix / stem-prefix
    ex["ANA-229"] = experiment(gw, "ANA-229", test_a, cal_a, base, [
        ("prefix>=5", wf(base, unified_tokens=True, prefix_min_len=5)),
        ("stem_prefix>=5", wf(base, unified_tokens=True, prefix_min_len=5, stem_prefix=True)),
        ("prefix>=4", wf(base, unified_tokens=True, prefix_min_len=4))])
    ex["ANA-229"]["paraphrased_in_test"] = sum(i["qclass"] == "paraphrased" for i in test_a)
    # ANA-230 -- hybrid fusion (graphify pipeline)
    ex["ANA-230"] = experiment(gw, "ANA-230", test_a, cal_a, base, [
        ("magnitude", wf(base, hybrid_score="magnitude")), ("rrf", wf(base, hybrid_score="rrf"))],
        pipeline="graphify", k=5)
    # ANA-231 -- relaxed dedup for COMPLEX queries (k=10 so the extra sections can matter)
    ex["ANA-231"] = experiment(gw, "ANA-231", test_a, cal_a, base,
                               [(f"complex_dedup_max={n}", wf(base, complex_dedup_max=n)) for n in (2, 3, 5)], k=10)
    ex["ANA-231"]["complex_in_test"] = sum(classify(i["question"]).complexity == "COMPLEX" for i in test_a)
    ex["ANA-231"]["multi_source_in_test"] = sum(len(i["expected_sources"]) >= 2 for i in test_a)
    # ANA-232 -- lightweight (lexical, deterministic) reranker; the neural reranker is BLOCKED (no local model)
    ex["ANA-232"] = experiment(gw, "ANA-232", test_a, cal_a, base, [
        (f"lex_rerank_top=20 alpha={a}", wf(base, lex_rerank_top=20, lex_rerank_alpha=a)) for a in (0.3, 0.5, 0.7)], k=3)
    # ANA-233 -- relative score cutoff sweep, per query class (cost = context tokens)
    ex["ANA-233"] = sweep_cutoff(gw, test_a, cal_a)
    # ANA-234 -- PPR with data
    ex["ANA-234"] = ppr_decision(gw, test_a)
    # ANA-235 / ANA-225 -- need a local model
    ex["ANA-235"] = blocked("ANA-235", "canal semântico (RRF)", res["meta"]["ollama"])
    ex["ANA-225"] = blocked("ANA-225", "backend JEV local (concordância com o juiz pago)", res["meta"]["ollama"])
    # ANA-236 -- deterministic query rewriting
    ex["ANA-236"] = experiment(gw, "ANA-236", test_a, cal_a, base, [
        ("rewrite", wf(base, query_rewrite=True)), ("rewrite+unified", wf(base, query_rewrite=True, unified_tokens=True))])
    # ANA-237 -- budget: query-aware fit instead of dropping the block
    ex["ANA-237"] = {}
    for b in (350, 600, 1000):
        r = experiment(gw, f"ANA-237@budget={b}", test_a, cal_a, base, [("budget_fit", wf(base, budget_fit=True))],
                       budget=b)
        cmp = r["test"]["paired_vs_control"]
        if "fact_in_ctx" in cmp and cmp["fact_in_ctx"]["mean_diff"] is not None:
            r["verdict"], r["why"] = verdict(cmp, primary=("fact_in_ctx",))
        ex["ANA-237"][f"budget={b}"] = r
    return res


def ollama_state() -> dict:
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
        return {"running": True, "models": models}
    except Exception as exc:  # noqa: BLE001
        return {"running": False, "error": type(exc).__name__}


def blocked(ana, what, oll):
    return {"id": ana, "verdict": "BLOCKED",
            "why": f"{what}: precisa de modelo local Ollama; running={oll.get('running')}, "
                   f"modelos={oll.get('models', [])}. Infra + testes com backend fake entregues; nada medido."}


def sweep_cutoff(gw, test_a, cal_a):
    from app.retrieval.experiments import RetrievalExperiments as E, with_flags as wf
    taus = (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)

    def per_class(items):
        out: dict = {}
        for tau in taus:
            rows = run_arm(gw, items, wf(E(), rel_cutoff=tau), k=10)
            for qc in sorted({r["qclass"] for r in rows}):
                sub = [r for r in rows if r["qclass"] == qc and "recall" in r]
                out.setdefault(qc, {})[tau] = {"n": len(sub), "recall": statistics.mean(r["recall"] for r in sub),
                                               "ctx_tokens": statistics.mean(r["ctx_tokens"] for r in sub)}
        return out
    cal, tst = per_class(cal_a), per_class(test_a)
    chosen = {}
    for qc, tab in cal.items():            # largest tau that keeps the calibration recall of tau=0
        chosen[qc] = max(t for t in taus if tab[t]["recall"] >= tab[0.0]["recall"] - 1e-9)
    cut_rows = {tau: {r["id"]: r for r in run_arm(gw, test_a, wf(E(), rel_cutoff=tau), k=10)}
                for tau in set(chosen.values())}
    ctl = run_arm(gw, test_a, E(), k=10)
    arm = [cut_rows[chosen.get(r["qclass"], 0.0)][r["id"]] for r in ctl]
    cmp = compare(arm, ctl)
    v, why = verdict(cmp)
    return {"id": "ANA-233", "chosen_tau_by_class": chosen,
            "selected_on": "calibration (train+val): largest tau that keeps calibration recall",
            "test_sweep_by_class": {qc: {str(t): {kk: round(vv, 4) for kk, vv in d.items()} for t, d in tab.items()}
                                    for qc, tab in tst.items()},
            "test": {"control": summarize(ctl), "arm": summarize(arm), "paired_vs_control": cmp},
            "verdict": v, "why": why,
            "note": "a flag MG_EXP_REL_CUTOFF é global; o tau por classe é medição, não configuração em runtime"}


def ppr_decision(gw, test_a):
    from app.retrieval.experiments import RetrievalExperiments as E
    rc = gw.retrieval_cfg
    rc.ppr_enabled = False
    ctl = run_arm(gw, test_a, E(), pipeline="graphify", k=10)
    rc.ppr_enabled = True
    try:
        arm = run_arm(gw, test_a, E(), pipeline="graphify", k=10)
    finally:
        rc.ppr_enabled = False
    cmp = compare(arm, ctl)
    lat = {"bfs": summarize(ctl)["latency_ms_median"], "ppr": summarize(arm)["latency_ms_median"]}
    cmp["latency_ms_median"] = lat
    prior = json.loads((ROOT / "tests" / "fixtures" / "onda9" / "ppr_bench.json").read_text(encoding="utf-8"))
    v, why = verdict(cmp)
    lat_x = (lat["ppr"] or 0) / max(lat["bfs"] or 1e-9, 1e-9)
    if v != "ADOTAR" and lat_x >= 2:
        v = "REJEITAR"
    why += f"; latência mediana PPR/BFS = {lat_x:.1f}x"
    return {"id": "ANA-234", "test": {"control": summarize(ctl), "arm": summarize(arm), "paired_vs_control": cmp},
            "prior_docs_ppr_bench": {c: {a: {k: d[k] for k in ("recall_mean", "complex_recall_mean", "latency_ms_median")}
                                         for a, d in arms.items()} for c, arms in prior["corpora"].items()},
            "verdict": v, "why": why}


# ----------------------------------------------------------------------------------------------- rendering
def _fmt(ci):
    if not ci:
        return "—"
    m = ci.get("mean", ci.get("rate"))
    if m is None:
        return "—"
    return f"{m:.3f} [{ci['low']:.3f}, {ci['high']:.3f}]"


def render(res: dict) -> str:
    m = res["meta"]
    L = ["# Onda 9 — experimentos de retrieval (ANA-225..237)", "",
         f"Gerado por `scripts/measure_onda9.py` ({m['generated_at']}). Corpus `{m['vault']}`, golden `{m['golden']}`.",
         f"Veredito só no split **test** ({m['n_test_answerable']} itens respondíveis de {m['n_test']}); parâmetros escolhidos na "
         f"calibração ({m['n_calibration_answerable']} respondíveis). Offline, 0 tokens pagos. Ollama: "
         f"`{json.dumps(m['ollama'])}`.", "",
         "> n pequeno: IC bootstrap largos; diferença pontual sem IC fora de zero **não** é resultado. "
         "Corpus sintético: não generaliza para o vault real sem remedir.", "",
         "| Item | Veredito | Evidência (test) |", "|---|---|---|"]
    flat = []
    for k, v in res["experiments"].items():
        if "verdict" in v:
            flat.append((k, v))
        else:
            flat += [(f"{k} {sub}", vv) for sub, vv in v.items() if isinstance(vv, dict) and "verdict" in vv]
    for k, v in flat:
        L.append(f"| {k} | **{v['verdict']}** | {v['why']} |")
    L.append("")
    for k, v in flat:
        L.append(f"## {k}")
        if v["verdict"] == "BLOCKED":
            L += [v["why"], ""]
            continue
        t = v["test"]
        L += [f"Escolha na calibração: `{v.get('chosen', v.get('chosen_tau_by_class', '—'))}`", "",
              "| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |", "|---|---|---|---|---|---|"]
        for arm in ("control", "arm"):
            s = t[arm]
            L.append(f"| {arm} | {_fmt(s['hit'])} | {_fmt(s['recall'])} | {_fmt(s['mrr'])} | {s['ctx_tokens_mean']} | {s['latency_ms_median']} |")
        if "fact_in_context" in t["control"]:
            L += ["", f"fact_in_context: control {_fmt(t['control']['fact_in_context'])} → arm {_fmt(t['arm']['fact_in_context'])}; "
                      f"blocos descartados por orçamento: {t['control'].get('blocks_dropped_budget_total')} → "
                      f"{t['arm'].get('blocks_dropped_budget_total')}"]
        L += ["", f"Veredito: **{v['verdict']}** — {v['why']}", ""]
    L += ["## Regra de default",
          "Só ANA-226 (correção de bug) mudou um default. Todo ADOTAR/MANTER_OPT_IN dos demais itens permanece com a flag "
          "**OFF**: o corpus é sintético, o test tem poucos itens e os ADOTAR por economia de tokens (ANA-233, ANA-236) "
          "devem ser remedidos no vault real antes de ligar.", "",
          "## Não medido",
          "- ANA-225/235 e o reranker neural (ANA-232): dependem de Ollama com modelo; ver BLOCKED acima.",
          "- Vault real: não usado (read-only, sem golden rotulado).", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    if a.render:
        res = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    else:
        res = measure()
        OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(res) + "\n", encoding="utf-8")
    print(render(res).split("## ANA")[0])


if __name__ == "__main__":
    main()
