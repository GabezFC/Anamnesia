"""Providers combinados: Hybrid (laya_then_jev | jev_then_laya | ensemble) e Adaptive (ANAM-043).

Regras comuns:
  * DROP/KEEP confiante do Laya NÃO vai ao JEV (é a economia de chamadas); QUARANTINE de qualquer lado vence.
  * Se UM lado cai, o outro decide e o item sai com `fallback=True` + `reason` (nunca silencioso).
    Se os DOIS caem, levanta ProviderUnavailable e o Engine aplica o fallback do tipo de operação.
  * `others` guarda a leitura de cada provider por item (insumo da análise de divergência).
  * Custo JEV em jev_then_laya e ensemble é igual ao do JEV-only: o ganho possível é de qualidade, não de custo.
"""
from __future__ import annotations

import time

from app.decision.base import DecisionProvider
from app.decision.config import STRATEGIES, DecisionConfig
from app.decision.providers import JEVDecisionProvider, LayaDecisionProvider
from app.decision.types import (DROP, KEEP, OP_RETRIEVAL, QUARANTINE, REVIEW, UNJUDGED, DecisionRequest,
                                DecisionResult, Item, ItemDecision, ProviderUnavailable)

HYBRID_VERSION = "hybrid-v1"
ADAPTIVE_VERSION = "adaptive-v1"
_VOTE = {KEEP: 1.0, REVIEW: 0.5, DROP: 0.0}


def _view(d: ItemDecision) -> dict:
    return {"decision": d.decision, "score": None if d.score is None else round(d.score, 4),
            "confidence": None if d.confidence is None else round(d.confidence, 4)}


def _sub(req: DecisionRequest, items: list[Item]) -> DecisionRequest:
    return DecisionRequest(req.query, items, req.op, req.project, req.schema, req.request_id)


def _try(p: DecisionProvider, req: DecisionRequest) -> tuple[DecisionResult | None, str]:
    if not req.items:
        return DecisionResult(req.request_id, req.op, p.provider_name, project=req.project), ""
    try:
        return p.decide(req), ""
    except ProviderUnavailable as exc:
        return None, str(exc)[:160]


def _merge_calls(res: DecisionResult, *parts: DecisionResult | None) -> None:
    for r in parts:
        if r is None:
            continue
        for k, v in r.calls.items():
            res.calls[k] = res.calls.get(k, 0) + v
        res.jev_requests += r.jev_requests
        res.errors += r.errors
        res.latency_ms += r.latency_ms


class _Composite(DecisionProvider):
    def __init__(self, cfg: DecisionConfig, jev: JEVDecisionProvider, laya: LayaDecisionProvider):
        self.cfg, self.jev, self.laya = cfg, jev, laya

    @property
    def checkpoint(self) -> str:
        return f"{self.laya.checkpoint}|{self.jev.checkpoint}"

    def health(self) -> dict:
        return {"provider": self.provider_name, "jev": self.jev.health(), "laya": self.laya.health()}

    def capabilities(self) -> dict:
        lc, jc = self.laya.capabilities(), self.jev.capabilities()
        return {"ops": sorted(set(lc["ops"]) | set(jc["ops"])), "batch": True,
                "provides_confidence": True, "paid": None,
                "note": "memory/security são decididos só pelo Laya; JEV só em retrieval (e security strict)"}

    # roteia ops não-retrieval ao Laya (JEV não suporta memory)
    def _non_retrieval(self, req: DecisionRequest) -> DecisionResult:
        r = self.laya.decide(req)
        r.provider = self.provider_name
        return r

    def _laya_first(self, req: DecisionRequest, strategy: str, th_key: str, escalate_review: bool = True) -> DecisionResult:
        th = self.cfg.thresholds_for(th_key, req.project)
        lres, lerr = _try(self.laya, req)
        res = DecisionResult(req.request_id, req.op, self.provider_name, strategy=strategy, project=req.project)
        by_id: dict[str, ItemDecision] = {}
        escalate: list[Item] = []
        lmap = {d.candidate_id: d for d in (lres.items if lres else [])}
        from app.services.injection_screen import screen
        for it in req.items:
            d = lmap.get(it.candidate_id)
            if d is None or d.decision == UNJUDGED:
                escalate.append(it)
                continue
            # recalcula a faixa com os limiares DESTA configuração (provider/projeto), preservando QUARANTINE
            if d.decision != QUARANTINE and d.score is not None:
                d.decision = th.band(d.score)
            confident = th.min_confidence <= 0 or (d.confidence is not None and d.confidence >= th.min_confidence)
            settled = (d.decision == DROP and confident) or (
                d.decision == QUARANTINE) or (
                d.decision == REVIEW and confident and not escalate_review) or (
                d.decision == KEEP and confident and not screen(it.text or "").suspicious)
            if settled:
                by_id[it.candidate_id] = d
            else:
                escalate.append(it)
        jres, jerr = _try(self.jev, _sub(req, escalate)) if escalate else (DecisionResult(req.request_id, req.op, "jev"), "")
        if lres is None and jres is None:
            raise ProviderUnavailable(f"Laya e JEV indisponíveis: {lerr} | {jerr}"[:240])
        jmap = {d.candidate_id: d for d in (jres.items if jres else [])}
        for it in escalate:
            ld, jd = lmap.get(it.candidate_id), jmap.get(it.candidate_id)
            if jd is not None:
                jd.escalated = True
                if ld is not None:
                    jd.others = {"laya": _view(ld)}
                if lres is None:
                    jd.fallback, jd.reason = True, "Laya indisponível: JEV decidiu"
                by_id[it.candidate_id] = jd
            else:   # JEV caiu: o que o Laya disse (REVIEW/baixa confiança) vale, sinalizado
                base = ld or ItemDecision(it.candidate_id, it.content_hash, UNJUDGED, provider="laya")
                base.fallback, base.escalated = True, True
                base.reason = (f"JEV indisponível: {jerr}"[:140])
                by_id[it.candidate_id] = base
        res.items = [by_id[i.candidate_id] for i in req.items]
        _merge_calls(res, lres, jres)
        if lerr:
            res.errors.append(f"laya: {lerr}")
        if jerr:
            res.errors.append(f"jev: {jerr}")
        return res


class HybridDecisionProvider(_Composite):
    @property
    def provider_name(self) -> str:
        return "hybrid"

    @property
    def version(self) -> str:
        return f"{HYBRID_VERSION}+{self.laya.version}+{self.jev.version}"

    def decide(self, request: DecisionRequest, strategy: str | None = None) -> DecisionResult:
        strat = strategy or self.cfg.provider_for(request.project)[1]
        if strat not in STRATEGIES:
            raise ValueError(f"estratégia inválida: {strat!r}")
        if request.op != OP_RETRIEVAL:
            return self._non_retrieval(request)
        t0 = time.perf_counter()
        res = {"laya_then_jev": lambda: self._laya_first(request, strat, "laya"),
               "jev_then_laya": lambda: self._jev_then_laya(request),
               "ensemble": lambda: self._ensemble(request)}[strat]()
        res.latency_ms = (time.perf_counter() - t0) * 1000
        return res

    def _jev_then_laya(self, req: DecisionRequest) -> DecisionResult:
        th = self.cfg.thresholds_for("laya", req.project)
        jres, jerr = _try(self.jev, req)
        res = DecisionResult(req.request_id, req.op, self.provider_name, strategy="jev_then_laya", project=req.project)
        if jres is None:   # JEV caiu: Laya decide tudo, sinalizado
            lres, lerr = _try(self.laya, req)
            if lres is None:
                raise ProviderUnavailable(f"JEV e Laya indisponíveis: {jerr} | {lerr}"[:240])
            for d in lres.items:
                d.fallback, d.reason = True, "JEV indisponível: Laya decidiu"
            res.items = lres.items
            _merge_calls(res, lres)
            res.errors.append(f"jev: {jerr}")
            return res
        undecided = [it for it, d in zip(req.items, jres.items) if d.decision == REVIEW]
        lres, lerr = _try(self.laya, _sub(req, undecided)) if undecided else (None, "")
        lmap = {d.candidate_id: d for d in (lres.items if lres else [])}
        for d in jres.items:
            ld = lmap.get(d.candidate_id)
            if ld is not None and ld.score is not None:
                d.others = {"laya": _view(ld)}
                tb = th.band(ld.score)   # Laya desempata só o REVIEW do JEV; nunca derruba KEEP/DROP do JEV
                if tb != REVIEW:
                    d.decision, d.escalated = tb, True
                    d.reason = "desempate Laya sobre REVIEW do JEV"
        res.items = jres.items
        _merge_calls(res, jres, lres)
        if lerr:
            res.errors.append(f"laya: {lerr}")
        return res

    def _ensemble(self, req: DecisionRequest) -> DecisionResult:
        th = self.cfg.thresholds_for("ensemble", req.project)
        wl, wj = self.cfg.ensemble_weights
        lth, jth = (self.cfg.thresholds_for("laya", req.project), self.cfg.thresholds_for("jev", req.project))
        lres, lerr = _try(self.laya, req)
        jres, jerr = _try(self.jev, req)
        if lres is None and jres is None:
            raise ProviderUnavailable(f"Laya e JEV indisponíveis: {lerr} | {jerr}"[:240])
        res = DecisionResult(req.request_id, req.op, self.provider_name, strategy="ensemble", project=req.project)
        lmap = {d.candidate_id: d for d in (lres.items if lres else [])}
        jmap = {d.candidate_id: d for d in (jres.items if jres else [])}
        for it in req.items:
            ld, jd = lmap.get(it.candidate_id), jmap.get(it.candidate_id)
            if ld is not None and ld.score is not None and ld.decision != QUARANTINE:
                ld.decision = lth.band(ld.score)
            if jd is not None and jd.score is not None and jd.decision != QUARANTINE:
                jd.decision = jth.band(jd.score)
            ok = [d for d in (ld, jd) if d is not None and d.decision in _VOTE or d is not None and d.decision == QUARANTINE]
            if any(d.decision == QUARANTINE for d in ok):
                q = next(d for d in ok if d.decision == QUARANTINE)
                out = ItemDecision(it.candidate_id, it.content_hash, QUARANTINE, q.score, None, "ensemble", "quarentena de " + q.provider)
            elif ld is not None and jd is not None and ld in ok and jd in ok:
                vote = (wl * _VOTE[ld.decision] + wj * _VOTE[jd.decision]) / ((wl + wj) or 1.0)
                out = ItemDecision(it.candidate_id, it.content_hash, th.band(vote), vote, None, "ensemble")
            elif ok:
                only = ok[0]
                out = ItemDecision(it.candidate_id, it.content_hash, only.decision, only.score, only.confidence,
                                   "ensemble", f"só {only.provider} respondeu", fallback=True)
            else:
                out = ItemDecision(it.candidate_id, it.content_hash, UNJUDGED, provider="ensemble", reason="nenhum respondeu")
            out.others = {k: _view(d) for k, d in (("laya", ld), ("jev", jd)) if d is not None}
            res.items.append(out)
        _merge_calls(res, lres, jres)
        if lerr:
            res.errors.append(f"laya: {lerr}")
        if jerr:
            res.errors.append(f"jev: {jerr}")
        return res


class AdaptiveDecisionProvider(_Composite):
    """Laya primeiro; JEV só nos itens com `confidence` < limiar (thresholds.adaptive.min_confidence) ou na faixa REVIEW."""

    @property
    def provider_name(self) -> str:
        return "adaptive"

    @property
    def version(self) -> str:
        return f"{ADAPTIVE_VERSION}+{self.laya.version}+{self.jev.version}"

    def decide(self, request: DecisionRequest) -> DecisionResult:
        if request.op != OP_RETRIEVAL:
            return self._non_retrieval(request)
        t0 = time.perf_counter()
        res = self._laya_first(request, "adaptive", "adaptive", escalate_review=False)
        res.latency_ms = (time.perf_counter() - t0) * 1000
        return res
