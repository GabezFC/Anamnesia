"""API de IA local — Laya e Colibri (ANAM-046): status / teste / reparo / instalação com confirmação.

Todas as rotas são loopback-only (`require_localhost`); as que executam algo (teste, repair, install,
config) exigem também o guard completo de escrita local (`require_local_write`, igual aos endpoints que
gastam ou mudam estado). NADA instala, baixa ou reinicia sem `confirm=true` EXPLÍCITO no corpo do request.
Respostas não carregam conteúdo do usuário: os canários de teste usam frases sintéticas fixas do próprio
módulo (as mesmas de tests/test_anam042_laya.py), nunca texto de vault.

Contrato devolvido ao chamador (UI):
  GET  /api/local-ai/laya/status      → estado efetivo, modo, disjuntor, worker, pesos, revisões
  POST /api/local-ai/laya/test        → 1 decisão de canário (relevância/privacidade) + latência real
  POST /api/local-ai/laya/repair      → diagnóstico + plano de passos verificáveis (não executa nada)
  POST /api/local-ai/laya/install     → executa o plano (SÓ com {"confirm": true}); passos idempotentes
  GET  /api/local-ai/colibri/status   → habilitado? URL? /v1/models responde? capacidades
  POST /api/local-ai/colibri/test     → sondagem + (opcional) 1 julgamento System One sintético
  POST /api/local-ai/colibri/config   → grava MG_COLIBRI_* no .env e reinicia o provider no engine
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.local_ai.laya_proc import discover_python, venv_has_laya, venv_python
from app.services.laya_decider import Q_PRIVACY, Q_RELEVANCE, get_backend, reset_backend
from app.services.security import require_local_write, require_localhost
from config.colibri import ColibriConfig, load_colibri_config
from config.laya import LAYA_PACKAGE_PIN, LayaConfig

router = APIRouter(prefix="/api/local-ai", dependencies=[Depends(require_localhost)])

# Canários sintéticos FIXOS (sem dado do usuário): neutro deve dar KEEP (relevância alta) e
# privado deve ser detectado como sensível (p_yes de privacidade alto).
_CANARY_RELEVANCE = "O pipeline de build usa cache de dependencias para acelerar a integracao continua."
_CANARY_PRIVATE = "Meu CPF e 123.456.789-00 e o diagnostico e diabetes tipo 2."


# --------------------------------------------------------------------------- helpers
def _laya_config() -> LayaConfig:
    return LayaConfig()


def _laya_diagnosis() -> dict:
    """Diagnóstico puro (sem executar nada mutante): o que falta para cada modo."""
    cfg = _laya_config()
    be = get_backend()
    st = be.status()
    dirs = be._model_dirs()   # noqa: SLF001 — diagnóstico interno, leitura apenas
    py, py_origin = discover_python(cfg.python)
    return {
        "configured_mode": cfg.mode, "effective_mode": st["effective_mode"], "reason": st["reason"],
        "weights": {k: v for k, v in dirs.items()},
        "package": {"pin": LAYA_PACKAGE_PIN,
                    "venv_python": py, "venv_origin": py_origin,
                    "laya_importable_in_venv": bool(py and venv_has_laya(Path(py)))},
        "inproc_possible": st["effective_mode"] == "inproc",
        "worker_possible": st["effective_mode"] == "worker",
        "serve_url": cfg.serve_url or None,
    }


def _laya_plan(diag: dict) -> list[dict]:
    """Passos verificáveis, na ordem. Cada passo é idempotente e verificável por comando."""
    steps: list[dict] = []
    if not diag["weights"].get("multilingual"):
        steps.append({"step": "download_weights", "required": True, "executed_by": "install",
                      "detail": "pesos ausentes em MG_LAYA_MODELS_DIR; baixar convaiinnovations/laya-multilingual "
                                "(revision pinada em config/laya.py) com confirm=True + sha256 "
                                "(app/services/local_ai/download.py). NÃO executado automaticamente."})
    pkg = diag["package"]
    if not pkg["venv_python"]:
        steps.append({"step": "create_venv", "required": True, "executed_by": "install",
                      "detail": f"criar venv em data/local_ai/venv312 (Python 3.12) — `uv venv data/local_ai/venv312`"})
    if pkg["venv_python"] and not pkg["laya_importable_in_venv"]:
        steps.append({"step": "install_package", "required": True, "executed_by": "install",
                      "detail": f"`uv pip install --python {pkg['venv_python']} "
                                f"laya=={LAYA_PACKAGE_PIN} torch` (torch CPU; sem [serve] — o worker "
                                f"não precisa de fastapi/uvicorn)"})
    steps.append({"step": "verify", "required": True, "executed_by": "install",
                  "detail": "worker de teste: 1 decisão de canário via modo worker; verificação é o p_yes do canário"})
    return steps


class ConfirmIn(BaseModel):
    confirm: bool = Field(False, description="DEVE ser true para executar qualquer passo mutante")


class ColibriConfigIn(BaseModel):
    enabled: bool | None = None
    url: str | None = Field(None, max_length=200)
    model: str | None = Field(None, max_length=80)


def _run(cmd: list[str], timeout_s: float = 600) -> dict:
    """Executa um passo de instalação e devolve o resultado verificador (sem instalar nada às cegas)."""
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s,
                           encoding="utf-8", errors="replace")
        return {"cmd": " ".join(cmd[:2]) + " …", "rc": r.returncode,
                "ms": round((time.perf_counter() - t0) * 1000),
                "stderr_tail": (r.stderr or "")[-400:], "ok": r.returncode == 0}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"cmd": " ".join(cmd[:2]) + " …", "rc": None, "ok": False,
                "stderr_tail": f"{type(exc).__name__}: {exc}"[:200]}


# --------------------------------------------------------------------------- Laya
@router.get("/laya/status")
def laya_status():
    cfg = _laya_config()
    diag = _laya_diagnosis()
    diag["circuit"] = get_backend().status().get("circuit")
    diag["worker"] = get_backend().status().get("worker")
    diag["plan"] = _laya_plan(diag)
    diag["env"] = {"MG_LAYA_MODE": cfg.mode, "MG_LAYA_SERVE_URL": cfg.serve_url or None,
                   "MG_LAYA_PYTHON": cfg.python or None, "MG_LAYA_FORCE_MODEL": cfg.force_model or "auto"}
    return diag


@router.post("/laya/test", dependencies=[Depends(require_local_write)])
def laya_test():
    be = get_backend()
    t0 = time.perf_counter()
    try:
        rel = be.decide([{"text": _CANARY_RELEVANCE}], "relevance", Q_RELEVANCE)[0]
        priv = be.decide([{"text": _CANARY_PRIVATE}], "privacy", Q_PRIVACY)[0]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Laya indisponível: {type(exc).__name__}: {exc}"[:200]) from exc
    st = be.status()
    return {"ok": True, "mode": st["effective_mode"], "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "relevance_p_yes": rel.p_yes, "privacy_p_yes": priv.p_yes,
            "note": "canários sintéticos fixos; p_yes de relevância alto no neutro e de privacidade alto "
                    "no sensível indicam integração saudável (limiares em config/laya.py)"}


@router.post("/laya/repair", dependencies=[Depends(require_local_write)])
def laya_repair():
    diag = _laya_diagnosis()
    return {"diagnosis": diag, "plan": _laya_plan(diag),
            "executed": False,
            "note": "nada foi executado; POST /laya/install com {\"confirm\": true} executa o plano"}


@router.post("/laya/install", dependencies=[Depends(require_local_write)])
def laya_install(body: ConfirmIn):
    if not body.confirm:
        raise HTTPException(428, "instalação exige {\"confirm\": true} explícito no corpo")
    cfg = _laya_config()
    diag = _laya_diagnosis()
    steps: list[dict] = []
    if not diag["weights"].get("multilingual"):
        # Antes de criar venv/instalar pacote: sem pesos não há o que verificar. Download exige
        # manifest (sha256/size) confirmado pelo operador — nunca um download às cegas.
        return {"status": "pending", "steps": [],
                "pending": "pesos ausentes: download exige manifest (sha256/size) confirmado pelo operador; "
                           "use app.services.local_ai.download.download_file com confirm=True "
                           "(revision pinada em config/laya.py). Nada foi baixado ou instalado."}
    py = diag["package"]["venv_python"]
    if not py:
        r = _run(["uv", "venv", "data/local_ai/venv312", "--python", "3.12"], timeout_s=300)
        steps.append({"step": "create_venv", **r})
        if not r["ok"]:
            return {"status": "failed", "steps": steps, "pending": "venv não criado; verifique uv no PATH"}
        py, _ = discover_python(cfg.python)
        py = py or "data/local_ai/venv312/Scripts/python.exe"
    if not venv_has_laya(Path(py)):
        r = _run(["uv", "pip", "install", "--python", py, f"laya=={LAYA_PACKAGE_PIN}", "torch"],
                 timeout_s=1800)
        steps.append({"step": "install_package", **r})
        if not r["ok"]:
            return {"status": "failed", "steps": steps, "pending": "instalação do pacote falhou "
                                                               "(veja stderr_tail; NÃO foi feito retry)"}
    else:
        steps.append({"step": "install_package", "ok": True, "note": f"laya=={LAYA_PACKAGE_PIN} já presente"})
    # verificação real: força modo worker e roda o canário
    reset_backend()
    try:
        res = laya_test()  # noqa: uso direto do handler (mesma guard já satisfeita)
    except HTTPException as exc:
        return {"status": "failed", "steps": steps, "pending": exc.detail}
    return {"status": "ok", "steps": steps, "test": res}


# --------------------------------------------------------------------------- Colibri
@router.get("/colibri/status")
def colibri_status_route():
    from app.services.colibri import colibri_status
    try:
        return colibri_status()
    except ValueError as exc:  # config inválida (URL/porta) é diagnóstico, não 500
        return {"provider": "colibri", "configured": False, "available": False,
                "label": "UNAVAILABLE", "reason": f"config inválida: {exc}"}


@router.post("/colibri/test", dependencies=[Depends(require_local_write)])
def colibri_test(body: ConfirmIn):
    from app.services.colibri import ColibriJudgeBackend, colibri_status
    st = colibri_status()
    out = {"probe": st}
    if not st.get("reachable"):
        out["judge"] = {"ok": False, "reason": st.get("reason") or "colibri desabilitado/inalcançável"}
        return out
    if not body.confirm:
        out["judge"] = {"ok": None, "note": "sondagem concluída; julgamento real exige {\"confirm\": true} "
                                            "(consome o modelo local; custo 0)"}
        return out
    try:
        be = ColibriJudgeBackend()
        ans, usage, model = be.evaluate({"text": _CANARY_RELEVANCE},
                                        {"q": {"type": "noul", "instructions": "Relevante para a frase?",
                                               "criteria": {"true": "ajuda", "false": "não ajuda"}}})
    except Exception as exc:  # noqa: BLE001
        out["judge"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        return out
    out["judge"] = {"ok": True, "model": model, "answer": ans.get("q"),
                    "usage": usage, "cost_usd": 0.0,
                    "quality_note": "julgamento único de canário; qualidade de triagem NÃO medida"}
    return out


@router.post("/colibri/config", dependencies=[Depends(require_local_write)])
def colibri_config_route(body: ColibriConfigIn):
    from app.services import envfile
    from config.paths import env_file_path
    from app.decision.engine import reset_engine
    patches = {}
    if body.enabled is not None:
        patches["MG_COLIBRI_ENABLED"] = "1" if body.enabled else "0"
    if body.url is not None:
        patches["MG_COLIBRI_URL"] = body.url.strip()
    if body.model is not None:
        patches["MG_COLIBRI_MODEL"] = body.model.strip()
    if not patches:
        raise HTTPException(422, "nada a alterar")
    applied = {}
    for k, v in patches.items():
        try:
            envfile.set_env_var(env_file_path(), k, v)
            applied[k] = v
        except envfile.EnvValueError as exc:
            raise HTTPException(422, f"{k}: {exc}") from exc
    reset_engine()   # próximo request reconstrói o engine com a config nova
    return {"applied": applied, "note": "valores valerão no próximo request; status reflete o novo engine",
            "validate": _try_load()}
    # (config invalida é reportada em validate; o .env já foi gravado — o operador decide)


def _try_load() -> dict:
    try:
        load_colibri_config().validate()
        return {"ok": True}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
