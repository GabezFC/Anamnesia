"""Benchmark local por fingerprint de hardware (ANAM-036).

Mede qualquer endpoint OpenAI-compativel (``/v1/chat/completions`` com ``stream=true``): TTFT,
prefill tok/s, decode tok/s e latencia total. Roda ``runs`` execucoes (padrao 3): a 1a e a *cold*
(carga do modelo / cache frio) e e DESCARTADA da media; as demais formam o *warm*. O relatorio traz
cold x warm e e gravado em ``data/local_ai/bench/<hw_fingerprint>.json`` (fingerprint de
``app.services.hw_profile``), para que a mesma maquina reaproveite o resultado.

Honestidade: o que o endpoint nao informa (ex.: sem ``usage``) vira ``"não medido"`` -- nunca um
numero estimado. Sem segredos no arquivo (a chave de API nao e gravada; a URL perde user:senha/query).

Testavel sem rede: o transporte e injetavel (``transport(request) -> iterable de chunks dict``) e o
relogio tambem. Os testes nunca chamam rede real.

Uso:  python -m app.benchmark.local_bench --base-url http://localhost:11434/v1 --model qwen2.5:7b
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterable, Optional

NOT_MEASURED = "não medido"
DEFAULT_PROMPT = ("Explique em um paragrafo curto o que e uma memoria de longo prazo para agentes de IA "
                  "e por que recuperar so as notas relevantes economiza tokens.")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = PROJECT_ROOT / "data" / "local_ai" / "bench"

Transport = Callable[[dict], Iterable[dict]]


# ------------------------------------------------------------------ transporte real (so no CLI)
def http_transport(base_url: str, api_key: str = "", timeout: float = 300.0) -> Transport:
    """Transporte SSE via urllib (stdlib). Nunca usado nos testes."""
    url = base_url.rstrip("/") + "/chat/completions"

    def run(request: dict) -> Iterable[dict]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=json.dumps(request).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - endpoint escolhido pelo usuario
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    return
                try:
                    yield json.loads(payload)
                except ValueError:
                    continue
    return run


# ------------------------------------------------------------------ medicao
def _content_of(chunk: dict) -> str:
    for ch in chunk.get("choices") or []:
        delta = ch.get("delta") or {}
        text = delta.get("content") or delta.get("reasoning_content") or ""
        if text:
            return text
    return ""


def measure_once(transport: Transport, model: str, prompt: str = DEFAULT_PROMPT, max_tokens: int = 128,
                 clock: Callable[[], float] = time.perf_counter) -> dict:
    """Uma execucao. Campos ausentes -> NOT_MEASURED (nunca estimados)."""
    request = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": True,
               "max_tokens": max_tokens, "temperature": 0,
               "stream_options": {"include_usage": True}}
    t0 = clock()
    t_first: Optional[float] = None
    usage: dict = {}
    try:
        for chunk in transport(request):
            if chunk.get("usage"):
                usage = chunk["usage"]
            if _content_of(chunk) and t_first is None:
                t_first = clock()
    except Exception as exc:  # noqa: BLE001 - falha do endpoint vira dado, nao excecao
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    t_end = clock()
    if t_first is None:
        return {"ok": False, "error": "nenhum token recebido"}
    ttft = t_first - t0
    decode_s = t_end - t_first
    p_tok, c_tok = usage.get("prompt_tokens"), usage.get("completion_tokens")
    return {
        "ok": True,
        "ttft_ms": round(ttft * 1000, 2),
        "latency_ms": round((t_end - t0) * 1000, 2),
        "prompt_tokens": p_tok if isinstance(p_tok, int) else NOT_MEASURED,
        "completion_tokens": c_tok if isinstance(c_tok, int) else NOT_MEASURED,
        "prefill_tok_s": round(p_tok / ttft, 2) if isinstance(p_tok, int) and ttft > 0 else NOT_MEASURED,
        # decode: tokens depois do 1o, divididos pelo tempo entre o 1o token e o fim
        "decode_tok_s": (round((c_tok - 1) / decode_s, 2)
                         if isinstance(c_tok, int) and c_tok > 1 and decode_s > 0 else NOT_MEASURED),
    }


_METRICS = ("ttft_ms", "latency_ms", "prefill_tok_s", "decode_tok_s")


def _mean(rows: list, key: str):
    vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.mean(vals), 2) if vals else NOT_MEASURED


def summarize_runs(rows: list) -> dict:
    """1a execucao = cold (descartada da media); o restante = warm. cold x warm lado a lado."""
    ok = [r for r in rows if r.get("ok")]
    out: dict = {"runs_total": len(rows), "runs_ok": len(ok), "discarded": "1a execucao (cold)"}
    cold = rows[0] if rows and rows[0].get("ok") else None
    warm = ok[(1 if cold else 0):]
    out["cold"] = {k: cold[k] for k in _METRICS} if cold else NOT_MEASURED
    out["warm"] = ({**{k: _mean(warm, k) for k in _METRICS}, "n": len(warm)} if warm else NOT_MEASURED)
    if cold and warm and isinstance(out["warm"]["ttft_ms"], (int, float)) and out["warm"]["ttft_ms"] > 0:
        out["cold_over_warm_ttft"] = round(cold["ttft_ms"] / out["warm"]["ttft_ms"], 2)
    else:
        out["cold_over_warm_ttft"] = NOT_MEASURED
    return out


def _safe_url(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    return urllib.parse.urlunsplit((p.scheme, host, p.path, "", ""))


def bench_path(fingerprint: str, directory: Path | str | None = None) -> Path:
    return Path(directory or BENCH_DIR) / f"{fingerprint}.json"


def run_benchmark(transport: Transport, model: str, base_url: str = "local", runs: int = 3,
                  prompt: str = DEFAULT_PROMPT, max_tokens: int = 128,
                  hw: Optional[dict] = None, out_dir: Path | str | None = None,
                  clock: Callable[[], float] = time.perf_counter, write: bool = True) -> dict:
    """Mede, resume e (opcional) grava em ``<out_dir>/<fingerprint>.json``. ``hw`` injetavel."""
    if hw is None:
        from app.services.hw_profile import detect_hardware
        hw = detect_hardware()
    fp = hw.get("hw_fingerprint") or NOT_MEASURED
    rows = [measure_once(transport, model, prompt, max_tokens, clock) for _ in range(max(2, int(runs)))]
    entry = {"model": model, "endpoint": _safe_url(base_url), "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "prompt_chars": len(prompt), "max_tokens": max_tokens, "runs": rows, **summarize_runs(rows)}
    path = bench_path(fp, out_dir)
    persist = write and fp != NOT_MEASURED
    doc: dict = {"schema": 1, "hw_fingerprint": fp,
                 "hardware": {k: hw.get(k) for k in ("os", "cpu", "ram", "gpus")}, "results": {}}
    if persist and path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev.get("results"), dict):
                doc["results"] = prev["results"]
        except (OSError, ValueError):
            pass
    doc["results"][model] = entry
    if persist:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    doc["path"] = str(path) if persist else None
    return doc


def load_cached(fingerprint: str, model: str, directory: Path | str | None = None) -> Optional[dict]:
    """Resultado ja medido nesta maquina (ou None)."""
    try:
        doc = json.loads(bench_path(fingerprint, directory).read_text(encoding="utf-8"))
        return (doc.get("results") or {}).get(model)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ ANAM-037: hit-rate antes x depois
def hotset_bench(vault: Path | str | None = None, questions: Path | str | None = None, requests: int = 400,
                 cache_size: int = 8, zipf_s: float = 1.2, seed: int = 7, touch_every: int = 100) -> dict:
    """Hit-rate do cache de resultados com o hotset desligado x ligado, mesma carga (Zipf), mesmo vault.

    Reusa ``scripts/bench_optimizer.py`` (make_gw) e mede recall nas mesmas perguntas respondiveis.
    O vault e COPIADO para um diretorio temporario: a cada ``touch_every`` pedidos uma nota e tocada
    (simula escrita -> reindex -> cache limpo), pois o vault real e somente leitura.
    """
    import random
    import shutil
    import sys
    import tempfile

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    sys.path.insert(0, str(PROJECT_ROOT))
    import bench_optimizer as bo  # noqa: WPS433
    from app.gateway import optimizer as optmod
    from config.benchmark import BenchmarkConfig
    from config.optimizer import OptimizerConfig
    from config.retrieval import RetrievalConfig
    from app.gateway.memory_gateway import MemoryGateway

    src = Path(vault or PROJECT_ROOT / "data" / "synthetic_vault")
    qs = json.loads(Path(questions or PROJECT_ROOT / "benchmark" / "synthetic_questions.json").read_text("utf-8"))
    rnd = random.Random(seed)
    weights = [1.0 / (i + 1) ** zipf_s for i in range(len(qs))]
    order = list(range(len(qs)))
    rnd.shuffle(order)                                   # which question is "popular" is arbitrary
    seq = rnd.choices(order, weights=[weights[order.index(i)] for i in range(len(qs))], k=requests)
    out: dict = {"requests": requests, "questions": len(qs), "cache_size": cache_size, "zipf_s": zipf_s,
                 "touch_every": touch_every, "arms": {}}
    for arm, on in (("hotset_off", False), ("hotset_on", True)):
        tmp = Path(tempfile.mkdtemp())
        v = tmp / "vault"
        shutil.copytree(src, v, ignore=shutil.ignore_patterns("graphify-out"))
        rc = RetrievalConfig(vault_path=v, data_dir=tmp / "data")
        bc = BenchmarkConfig(db_path=str(tmp / "b.db"), profile="production", benchmark_mode=False)
        gw = MemoryGateway(retrieval_cfg=rc, bench_cfg=bc, optimizer_cfg=OptimizerConfig().with_(
            cache_size=cache_size, refresh_interval_s=0.0))
        gw.optimizer.hotset = None
        gw.optimizer.cache.score_fn = None
        if on:
            gw.optimizer.enable_hotset()
        gw.warm()
        touch = next(v.rglob("*.md"))
        recalls, lat, user_hits = [], [], 0
        for n, qi in enumerate(seq, 1):
            if touch_every and n % touch_every == 0:
                with touch.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n<!-- touch {n} -->\n")
            q = qs[qi]
            t0 = time.perf_counter()
            r = gw.search(q["question"], "auto", 10, persist=False)
            lat.append((time.perf_counter() - t0) * 1000)
            user_hits += bool(r.metrics.get("result_cache_hit"))
            exp = q.get("expected_sources") or []
            if q.get("answerable", True) and exp:
                files = [s.file for s in r.sources]
                recalls.append(sum(e in files for e in exp) / len(exp))
        st = gw.optimizer.cache.stats()
        out["arms"][arm] = {"hit_rate": round(user_hits / len(seq), 4), "hits": user_hits, "misses": len(seq) - user_hits,
                            "cache_lookups_incl_prewarm": st["hits"] + st["misses"],
                            "recall_mean": round(statistics.mean(recalls), 4) if recalls else NOT_MEASURED,
                            "latency_ms_mean": round(statistics.mean(lat), 2),
                            "latency_ms_median": round(statistics.median(lat), 2),
                            "protected_evictions": gw.optimizer.cache.protected_evictions,
                            "prewarmed_queries": gw.optimizer.prewarmed}
        shutil.rmtree(tmp, ignore_errors=True)
    a, b = out["arms"]["hotset_off"], out["arms"]["hotset_on"]
    out["delta"] = {"hit_rate": round((b["hit_rate"] or 0) - (a["hit_rate"] or 0), 4),
                    "recall": (round(b["recall_mean"] - a["recall_mean"], 4)
                               if isinstance(a["recall_mean"], float) and isinstance(b["recall_mean"], float)
                               else NOT_MEASURED)}
    out["hotset_default"] = optmod.HOTSET_DEFAULT
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark de endpoint OpenAI-compativel (ANAM-036)")
    ap.add_argument("--hotset-bench", action="store_true", help="ANAM-037: hit-rate hotset off x on (sem rede)")
    ap.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "http://localhost:11434/v1"))
    ap.add_argument("--model", default=None)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--out-dir", default=None)
    a = ap.parse_args(argv)
    if a.hotset_bench:
        print(json.dumps(hotset_bench(), ensure_ascii=False, indent=2))
        return 0
    if not a.model:
        ap.error("--model e obrigatorio")
    doc = run_benchmark(http_transport(a.base_url, os.environ.get("OPENAI_API_KEY", "")), a.model, a.base_url,
                        runs=a.runs, max_tokens=a.max_tokens, out_dir=a.out_dir)
    print(json.dumps({**doc["results"][a.model], "path": doc["path"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
