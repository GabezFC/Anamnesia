"""ANAM-014/015/017 -- medições antes/depois (cache JEV, fusão híbrida, near-dup, FTS prefixo, cosseno).

    python scripts/bench_anam_014_015_017.py --label antes  --out data/reports-out/anam-014-015-017_antes.json
    python scripts/bench_anam_014_015_017.py --label depois --out data/reports-out/anam-014-015-017_depois.json

Determinístico e offline (sem juiz, sem modelo, zero tokens). Latências são medianas de N repetições
(ruído típico de ±15% nesta máquina; só diferenças maiores contam). Cada bloco é tolerante a API ausente
(roda tanto no código antigo quanto no novo).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def med(fn, n=5):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t) * 1000)
    return round(st.median(xs), 2)


def bench_near_dup() -> dict:
    """Recall de pares com edição por substituição aleatória. `recall_vs_arbiter` = detectados / pares cuja
    similarity() (o árbitro) já passa do limiar: isola a GERAÇÃO de pares do limiar de decisão."""
    import inspect
    from app.schemas.models import Candidate
    from app.services.near_dup import cluster_near_duplicates, similarity
    has_lsh = "lsh" in inspect.signature(cluster_near_duplicates).parameters
    rnd = random.Random(7)
    words = [f"w{i}" for i in range(400)]
    mk = lambda n=120: [rnd.choice(words) for _ in range(n)]          # noqa: E731
    cand = lambda i, t, sc: Candidate(candidate_id=i, source_file=f"{i}.md", section="s", snippet=t, score=sc, origin="x")  # noqa: E731
    pairs = {}
    for p in (0.02, 0.05, 0.08, 0.12, 0.2):
        ps = []
        for _ in range(60):
            a = mk()
            ps.append((" ".join(a), " ".join((rnd.choice(words) if rnd.random() < p else x) for x in a)))
        pairs[p] = ps
    indep = [(" ".join(mk()), " ".join(mk())) for _ in range(60)]
    cs = [cand(f"c{i}", " ".join(mk(150)), 1 - i / 100) for i in range(25)]
    cs120 = [cand(f"c{i}", " ".join(mk(150)), 1 - i / 200) for i in range(120)]
    res: dict = {}
    for mode in ([False, True] if has_lsh else [None]):
        kw = {} if mode is None else {"lsh": mode}
        out = {}
        for thr in (0.88, 0.75):
            row = {}
            for p, ps in pairs.items():
                det = tot = 0
                for a, b in ps:
                    ok = similarity(a, b) >= thr
                    got = cluster_near_duplicates([cand("a", a, 1.0), cand("b", b, .9)], threshold=thr, **kw)[1]["dedup_near_collapsed"]
                    tot += ok
                    det += got and ok
                row[str(p)] = {"detected_pct": round(100 * det / len(ps), 1),
                               "recall_vs_arbiter": round(det / tot, 3) if tot else None, "pairs_over_threshold": tot}
            out[f"thr{thr}"] = row
        fp = sum(cluster_near_duplicates([cand("a", a, 1.0), cand("b", b, .9)], threshold=0.88, **kw)[1]["dedup_near_collapsed"]
                 for a, b in indep)
        out["false_positive_independent_pairs_of_60"] = fp
        out["cluster_25cands_ms"] = med(lambda: cluster_near_duplicates(cs, threshold=0.88, **kw))
        out["cluster_120cands_ms"] = med(lambda: cluster_near_duplicates(cs120, threshold=0.88, **kw), 3)
        res["default" if mode is None else ("lsh_on" if mode else "lsh_off")] = out
    return res


def bench_cosine() -> dict:
    rnd = random.Random(3)
    d = 768
    vs = [[rnd.random() - .5 for _ in range(d)] for _ in range(2000)]
    q = [rnd.random() - .5 for _ in range(d)]
    from app.retrieval import experiments as E
    res = {"cosine_experiments_2000x768_ms": med(lambda: sorted(((E.cosine(q, v), i) for i, v in enumerate(vs)), reverse=True), 3)}
    try:
        from app.retrieval.similarity import normalize, rank_by_cosine
        nv = [normalize(v) for v in vs]
        res["rank_by_cosine_prenormalized_2000x768_ms"] = med(lambda: rank_by_cosine(q, nv), 5)
        a = rank_by_cosine(q, nv)[:20]
        b = sorted(((E.cosine(q, v), i) for i, v in enumerate(vs)), reverse=True)[:20]
        res["top20_identical_to_legacy"] = [i for _, i in a] == [i for _, i in b]
    except ImportError:
        pass
    return res


def bench_fts() -> dict:
    rnd = random.Random(7)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE sec USING fts5(file UNINDEXED, section, body, status UNINDEXED, line UNINDEXED,"
                 " tokenize='unicode61 remove_diacritics 2')")
    vocab = [f"t{i}" for i in range(3000)]
    zipf = [1 / (i + 1) for i in range(3000)]
    conn.executemany("INSERT INTO sec VALUES (?,?,?,?,?)", [
        (f"n{i // 5}.md", f"h{i}", " ".join(rnd.choices(vocab, weights=zipf, k=150)), "", i) for i in range(10000)])
    conn.commit()
    sql = "SELECT file,bm25(sec,0.0,2.0,1.0,0.0,0.0) r FROM sec WHERE sec MATCH ? ORDER BY r LIMIT 100"
    res = {"fts_prefix_t30*_ms": med(lambda: conn.execute(sql, ("t30*",)).fetchall(), 10),
           "fts_or_exact_4terms_ms": med(lambda: conn.execute(sql, ('"t5" OR "t40" OR "t300" OR "t1500"',)).fetchall(), 10)}
    # ANAM-017: a expansão de prefixo via fts5vocab foi medida e NÃO ajuda (ver docs/bench/anam-017.md); o custo
    # do prefixo vem do volume de documentos casados, não da varredura do vocabulário.
    res["fts_prefix_t30*_ms"] = med(lambda: conn.execute(sql, ("t30*",)).fetchall(), 10)
    res["fts_prefix_t30*_rows_matched"] = conn.execute("SELECT COUNT(*) FROM sec WHERE sec MATCH 't30*'").fetchone()[0]
    res["fts_prefix_t1*_rows_matched"] = conn.execute("SELECT COUNT(*) FROM sec WHERE sec MATCH 't1*'").fetchone()[0]
    res["fts_or_exact_rows_matched"] = conn.execute("""SELECT COUNT(*) FROM sec WHERE sec MATCH '"t5" OR "t40" OR "t300" OR "t1500"'""").fetchone()[0]
    return res


def bench_cache() -> dict:
    from app.services.jev_cache import CacheIdentity, LayeredCache
    ident = CacheIdentity(model="m", prompt_version="p", jev_mode="x", relevance_threshold=0.5, review_threshold=0.3)
    store: dict = {}
    ops = {"get": 0, "put": 0}

    def g(k):
        ops["get"] += 1
        return store.get(k)

    def p(k, v):
        ops["put"] += 1
        store[k] = v

    kw = {}
    try:
        import inspect
        if "get_many" in inspect.signature(LayeredCache.__init__).parameters:
            def gm(keys):
                ops["get"] += 1
                return {k: store[k] for k in keys if k in store}

            def pm(items):
                ops["put"] += 1
                store.update(items)
            kw = {"get_many": gm, "put_many": pm}
    except Exception:  # noqa: BLE001
        pass
    cache = LayeredCache(g, p, ident, **kw)
    n = 25
    hashes = [f"h{i}" for i in range(n)]
    q = "migrar de mysql para postgres"
    for h in hashes:
        if cache.get_judgement(q, h)[0] is None:
            cache.put_judgement(q, h, {"relevance": 0.2, "injection": None})
    res = {"cold_ops_per_candidate": {"get": ops["get"] / n, "put": ops["put"] / n}}
    ops["get"] = ops["put"] = 0
    for h in hashes:
        cache.get_judgement(q, h)
    res["warm_gets_per_candidate"] = ops["get"] / n
    rev = "migrar de postgres para mysql"
    res["direction_swapped_query_hit_rate"] = sum(cache.get_judgement(rev, h)[0] is not None for h in hashes) / n
    res["l2_order_collision_mysql_postgres"] = res["direction_swapped_query_hit_rate"] > 0
    res["pure_reorder_hit_rate"] = sum(cache.get_judgement("redis licenca versao", h)[0] is not None for h in hashes) / n
    cache.put_judgement("versao licenca redis", "hx", {"relevance": 0.1})
    res["non_directional_reorder_still_hits"] = cache.get_judgement("redis licenca versao", "hx")[0] is not None
    return res


def bench_hybrid() -> dict:
    """recall/MRR no golden-v2 (test + calibração) para fusão por rank (legado), magnitude e rrf."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "experiments"))
    import measure_onda9 as M
    from app.benchmark import golden
    from app.retrieval.experiments import RetrievalExperiments as E, with_flags as wf
    gw = M.make_gw()
    items = [i for i in golden.load(split="train") + golden.load(split="val") + golden.load(split="test")
             if i["answerable"] and i.get("expected_sources")]
    out = {"n_items": len(items)}
    for name, flags in (("rank_legado", E()), ("magnitude", wf(E(), hybrid_score="magnitude")),
                        ("rrf", wf(E(), hybrid_score="rrf"))):
        rows = M.run_arm(gw, items, flags, pipeline="graphify", k=5)
        ans = [r for r in rows if "recall" in r]
        out[name] = {"recall": round(st.mean(r["recall"] for r in ans), 4), "mrr": round(st.mean(r["mrr"] for r in ans), 4),
                     "hit": round(st.mean(r["hit"] for r in ans), 4),
                     "lat_ms_median": round(st.median(r["lat_ms"] for r in rows), 2)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="antes")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    blocks = {"near_dup": bench_near_dup, "cosine": bench_cosine, "fts": bench_fts, "cache": bench_cache,
              "hybrid": bench_hybrid}
    res = {"label": a.label, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "python": sys.version.split()[0]}
    for k, fn in blocks.items():
        if a.only and k not in a.only.split(","):
            continue
        try:
            res[k] = fn()
        except Exception as e:  # noqa: BLE001
            res[k] = {"error": f"{type(e).__name__}: {e}"}
    txt = json.dumps(res, indent=1, ensure_ascii=False)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    math  # noqa: B018
    main()
