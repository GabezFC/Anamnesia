"""Worker do Laya (processo-filho, JSON por linha). Roda no Python que TEM `laya`+`torch` (ex.: data/local_ai/venv312).

Autocontido de propósito: só stdlib + `laya`; NÃO importa `app`/`config` (o venv do Laya não tem as deps do Gateway).
Protocolo (uma linha JSON por mensagem, UTF-8):
  worker -> {"ready": true, "load_ms": N, "laya": "0.4.8", "models": ["multilingual"]}      (após carregar os pesos)
  gateway -> {"id": N, "requests": [{"state":..., "questions":{...}, "model"?: ...}], "batch_size": 16}
  worker -> {"id": N, "results": [...]}   |   {"id": N, "error": "Tipo: mensagem"}
Argumentos: --multilingual DIR [--english DIR] [--device cpu] [--threads N]. Sem rede: pesos locais, nada é baixado.
EOF no stdin encerra o processo.
"""
from __future__ import annotations

import argparse
import json
import sys
import time


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--multilingual", required=True)
    ap.add_argument("--english", default="")
    ap.add_argument("--device", default="")
    ap.add_argument("--threads", type=int, default=0)
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    try:
        if a.threads > 0:
            import torch
            torch.set_num_threads(a.threads)
        import laya
        from laya import Router
        models = {"multilingual": a.multilingual}
        if a.english:
            models["english"] = a.english
        router = Router(models=models, default="multilingual", device=a.device or None)
    except Exception as exc:  # noqa: BLE001 — erro de carga vira mensagem estruturada, nunca traceback no pipe
        _emit({"ready": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 2
    _emit({"ready": True, "load_ms": round((time.perf_counter() - t0) * 1000, 1),
           "laya": getattr(laya, "__version__", ""), "models": sorted(models)})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            res = router.predict_batch(msg["requests"], batch_size=msg.get("batch_size"))
            _emit({"id": msg.get("id"), "results": res})
        except Exception as exc:  # noqa: BLE001
            mid = None
            try:
                mid = msg.get("id")  # type: ignore[name-defined]
            except Exception:  # noqa: BLE001
                pass
            _emit({"id": mid, "error": f"{type(exc).__name__}: {exc}"[:300]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
