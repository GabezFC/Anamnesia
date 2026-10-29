"""Providers primários: JEV e Laya (ANAM-043). Reutilizam JevService e app/services/laya_decider.py sem alterá-los.

Os limiares vêm do `DecisionConfig` (por provider e por projeto), NÃO dos configs de cada serviço: assim a
mesma probabilidade pode ser lida com limiares diferentes por projeto sem tocar nos pipelines existentes.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from app.decision.base import DecisionProvider
from app.decision.config import DecisionConfig
from app.decision.types import (DROP, KEEP, MEASURED, OP_MEMORY, OP_RETRIEVAL, OP_SECURITY, QUARANTINE, REVIEW,
                                UNJUDGED, UNKNOWN, DecisionRequest, DecisionResult, Item, ItemDecision,
                                ProviderUnavailable, labeled)
from app.schemas.models import Candidate

JEV_DECISION_VERSION = "jev-decision-v1"
LAYA_DECISION_VERSION = "laya-decision-v1"


def jev_static_checks() -> dict:
    """Pre-requisitos do JEV verificaveis SEM rede e SEM custo (a sonda real e uma chamada paga/remota e so roda
    com consentimento: POST /api/decision/decision ou /api/local-ai/colibri/test para o backend local).
    Deterministico: chave ausente em backend remoto => INDISPONIVEL (nao 'nao sondado')."""
    import os
    from config.jev import JevConfig
    from app.services.jev import is_local_base_url, sdk_version
    cfg = JevConfig()
    base = os.environ.get("TYPESAFE_BASE_URL") or ""
    local = is_local_base_url(base) or cfg.backend == "ollama"
    key = bool(os.environ.get("TYPESAFE_API_KEY"))
    sdk = sdk_version()
    checks = {"backend": cfg.backend, "api_key_set": key, "local_backend": local, "sdk_version": sdk,
              "probe": "paid_not_run" if not local else "local_probe_available"}
    if cfg.backend == "typesafe" and not local and not key:
        return {**checks, "available": False, "label": "UNAVAILABLE",
                "reason": "TYPESAFE_API_KEY ausente e backend remoto: JEV indisponível (sem chamada; defina a chave ou use "
                          "JEV_BACKEND=ollama / TYPESAFE_BASE_URL loopback)"}
    if cfg.backend == "typesafe" and sdk is None:
        return {**checks, "available": False, "label": "UNAVAILABLE",
                "reason": "pacote typesafe_sdk não instalado neste Python"}
    why = ("pré-requisitos locais presentes; conectividade/qualidade NÃO sondadas "
           + ("(backend local: use a sonda gratuita)" if local else "(sonda real é chamada paga; exige ANAMNESIA_PAID_CALLS=1)"))
    return {**checks, "reason": why}


def to_candidates(items: list[Item]) -> list[Candidate]:
    return [Candidate(candidate_id=i.candidate_id, source_file=i.source or i.candidate_id, section=i.section,
                      snippet=i.text, content_hash=i.content_hash) for i in items]


class JEVDecisionProvider(DecisionProvider):
    """Juiz JEV (TypeSafe ou Colibrì local) via `JevService.evaluate`. Pago quando o backend é remoto."""

    def __init__(self, cfg: DecisionConfig, jev: Any | None = None, jev_factory: Callable[[], Any] | None = None,
                 label: str = "jev", name: str = "jev", health_fn: Callable[[], dict] | None = None):
        # `name` identifica o provider no engine/cache ("jev" pago ou "colibri" local); `label` é só exibição.
        self.cfg, self._jev, self._factory, self._label, self._name, self._health_fn = \
            cfg, jev, jev_factory, label, name, health_fn

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return JEV_DECISION_VERSION

    @property
    def checkpoint(self) -> str:
        j = self._jev
        return str(getattr(getattr(j, "cfg", None), "model", "") or self._label)

    def bind(self, jev: Any) -> None:
        self._jev = jev

    def _service(self):
        if self._jev is None and self._factory is not None:
            self._jev = self._factory()
        if self._jev is None:
            raise ProviderUnavailable("JEV não configurado (sem serviço injetado)")
        return self._jev

    def capabilities(self) -> dict:
        strict = False
        if self._jev is not None or self._factory is not None:
            try:
                strict = getattr(getattr(self._service(), "cfg", None), "mode", "") == "strict"
            except Exception:  # noqa: BLE001 — indisponibilidade não muda as capacidades declaradas
                pass
        return {"ops": [OP_RETRIEVAL] + ([OP_SECURITY] if strict else []), "batch": True, "local": None,
                "paid": None, "provides_confidence": False,
                "notes": "memory não suportado; security só com jev_mode=strict; custo/local depende de TYPESAFE_BASE_URL"}

    def health(self) -> dict:
        if self._health_fn is not None:
            try:
                return self._health_fn()
            except Exception as exc:  # noqa: BLE001 — sondagem nunca derruba o status
                return {"provider": self._name, "configured": True, "available": False,
                        "label": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"[:160], "backend": self._label}
        configured = self._jev is not None or self._factory is not None
        out = {"provider": self._name, "configured": configured, "available": None, "label": UNKNOWN,
               "reason": "não sondado: status não faz chamada ao JEV (nem paga)", "backend": self._label}
        if self._name == "jev":
            out.update(jev_static_checks())
        return out

    def decide(self, request: DecisionRequest) -> DecisionResult:
        if request.op not in self.capabilities()["ops"] and request.op != OP_SECURITY:
            raise ProviderUnavailable(f"JEV não suporta op={request.op}")
        svc = self._service()
        if request.op == OP_SECURITY and getattr(getattr(svc, "cfg", None), "mode", "") != "strict":
            raise ProviderUnavailable(f"{self._name} security exige jev_mode=strict")
        th = self.cfg.thresholds_for("colibri" if self._name == "colibri" else "jev", request.project)
        cands = to_candidates(request.items)
        t0 = time.perf_counter()
        try:
            _, m = svc.evaluate(request.query, cands)
        except Exception as exc:  # noqa: BLE001 — falha do juiz = indisponibilidade explícita
            raise ProviderUnavailable(f"JEV: {type(exc).__name__}: {exc}"[:200]) from exc
        lat = (time.perf_counter() - t0) * 1000
        errs = list(getattr(m, "errors", None) or [])
        if cands and all(c.relevance is None for c in cands) and errs:
            raise ProviderUnavailable(f"JEV sem resposta: {errs[0]}"[:200])
        inj_thr = getattr(getattr(svc, "cfg", None), "injection_threshold", 0.8)
        out = []
        for it, c in zip(request.items, cands):
            if request.op == OP_SECURITY:
                d = QUARANTINE if (c.injection or 0) >= inj_thr else (KEEP if c.injection is not None else UNJUDGED)
                score = c.injection
            else:
                d = QUARANTINE if c.decision == QUARANTINE else th.band(c.relevance)
                score = c.relevance
            out.append(ItemDecision(it.candidate_id, it.content_hash, d, score, None, self._name,
                                    reason="" if d != UNJUDGED else "sem resposta do JEV"))
        res = DecisionResult(request.request_id, request.op, "jev", project=request.project, items=out,
                             latency_ms=lat, calls={self._name: len(out)}, errors=errs[:3],
                             jev_requests=int(getattr(m, "request_count", 1) or 0))
        return res


class LayaDecisionProvider(DecisionProvider):
    """Laya local (não generativo) via app/services/laya_decider.py. Zero token pago."""

    def __init__(self, cfg: DecisionConfig, service: Any | None = None, backend: Any | None = None):
        self.cfg, self._service_obj, self._backend = cfg, service, backend

    @property
    def provider_name(self) -> str:
        return "laya"

    @property
    def version(self) -> str:
        return f"{LAYA_DECISION_VERSION}+{self._prompt_version()}"

    @staticmethod
    def _prompt_version() -> str:
        from config.laya import LAYA_PROMPT_VERSION
        return LAYA_PROMPT_VERSION

    @property
    def checkpoint(self) -> str:
        from config.laya import LAYA_REVISIONS
        return ",".join(f"{k}@{v[1][:8]}" for k, v in sorted(LAYA_REVISIONS.items()))

    def bind(self, service: Any) -> None:
        self._service_obj = service

    def _svc(self):
        if self._service_obj is None:
            from app.services.laya_decider import LayaService, get_backend
            from config.laya import LayaConfig
            be = self._backend or get_backend()
            self._service_obj = LayaService(LayaConfig(), be)
        return self._service_obj

    def _be(self):
        return self._svc().backend

    def capabilities(self) -> dict:
        return {"ops": [OP_RETRIEVAL, OP_MEMORY, OP_SECURITY], "batch": True, "local": True, "paid": False,
                "provides_confidence": True,
                "quality": labeled(0.64, MEASURED, "AUC relevância 0,64–0,68 vs lexical 0,975 (docs/bench/anam-042-laya.md; corpus sintético)")}

    def health(self) -> dict:
        try:
            st = self._be().status()
        except Exception as exc:  # noqa: BLE001
            return {"provider": "laya", "available": False, "label": MEASURED, "reason": f"{type(exc).__name__}: {exc}"[:160]}
        return {"provider": "laya", "available": st["effective_mode"] != "off", "label": MEASURED,
                "mode": st["effective_mode"], "reason": st["reason"], "errors": st["errors"],
                "prompt_version": st["prompt_version"]}

    def decide(self, request: DecisionRequest) -> DecisionResult:
        t0 = time.perf_counter()
        fn = {OP_RETRIEVAL: self._retrieval, OP_MEMORY: self._memory, OP_SECURITY: self._security}[request.op]
        items, errs = fn(request)
        return DecisionResult(request.request_id, request.op, "laya", project=request.project, items=items,
                              latency_ms=(time.perf_counter() - t0) * 1000, calls={"laya": len(items)}, errors=errs)

    def _retrieval(self, req: DecisionRequest):
        svc = self._svc()
        th = self.cfg.thresholds_for("laya", req.project)
        cands = to_candidates(req.items)
        answers, m = svc.score(req.query, cands)
        if cands and all(a is None for a in answers):
            raise ProviderUnavailable(f"Laya indisponível: {m.error or svc.backend.resolve_mode()}"[:200])
        out = []
        for it, c, a in zip(req.items, cands, answers):
            if a is None:
                out.append(ItemDecision(it.candidate_id, it.content_hash, UNJUDGED, provider="laya", reason="Laya sem resposta"))
                continue
            d, reason = th.band(a.p_yes), ""
            if d != DROP:  # mesmo gate do LayaService.evaluate: sinal lexical de injeção -> pergunta ao Laya
                quarantine, why = svc.injection_gate(c)
                if quarantine:
                    d, reason = QUARANTINE, why
            out.append(ItemDecision(it.candidate_id, it.content_hash, d, a.p_yes, a.confidence, "laya", reason))
        return out, ([m.error] if m.error else [])

    def _memory(self, req: DecisionRequest):
        from app.services.laya_decider import triage_write
        out = []
        for it in req.items:
            t = triage_write(it.text, self._be(), self._svc().cfg)
            d = {"allow": KEEP, "warn": REVIEW, "block": DROP}[t.action]
            s = max([x for x in (t.laya_injection, t.laya_junk) if x is not None], default=None)
            down = any(r.startswith("laya_unavailable") for r in t.reasons)
            if down and d == KEEP:   # Laya caiu: as regras sozinhas não bastam para gravar memória -> REVIEW explícito
                d = REVIEW
            out.append(ItemDecision(it.candidate_id, it.content_hash, d, s, None, "laya", ";".join(t.reasons)[:160],
                                    fallback=down, fallback_action="review" if down else ""))
        return out, []

    def _security(self, req: DecisionRequest):
        from app.services.laya_decider import classify_privacy
        out = []
        for it in req.items:
            v = classify_privacy(it.text, self._be(), self._svc().cfg)
            fb = v.source == "fail_closed"
            out.append(ItemDecision(it.candidate_id, it.content_hash, QUARANTINE if v.private else KEEP, v.score, None,
                                    "laya", f"{v.source}:{','.join(v.signals)}"[:160], fallback=fb,
                                    fallback_action="block" if fb else ""))
        return out, []
