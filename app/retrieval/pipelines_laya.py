"""Pipelines com o decisor local Laya (ANAM-042).

    graphify_laya      graphify -> prefilter -> Laya (relevância + gate de injeção) -> sobreviventes.
                       Nenhum token pago: Laya roda local, sem geração.
    graphify_laya_jev  graphify -> prefilter -> Laya em TODOS; só os INCERTOS (p entre os limiares, ou
                       `confidence` < MG_LAYA_MIN_CONFIDENCE) e os KEEP com sinal lexical de injeção vão
                       ao JEV. DROP/KEEP confiantes e limpos nunca pagam o JEV.

Laya indisponível (off, pacote/pesos/servidor ausentes): `graphify_laya` aplica MG_LAYA_FAILURE_MODE
(fail_open passa os candidatos SINALIZADOS com `laya_fallback=1`); `graphify_laya_jev` escalona TUDO ao
JEV (equivale a `graphify_jev`) e também registra `laya_fallback=1`. Nada é silencioso.
"""
from __future__ import annotations

import time
from typing import Any

from app.retrieval.common import _graphify_candidates, _tokens, full_note_text
from app.retrieval.registry import register_pipeline
from app.schemas.models import Candidate
from app.services.injection_screen import screen
from app.services.jev import QUARANTINE
from app.services.laya_decider import (DROP, KEEP, REVIEW, UNJUDGED, LayaMetrics, LayaService, band,
                                       get_backend)
from app.services.prefilter import prefilter
from config.laya import LayaConfig


def laya_service(gw) -> LayaService:
    """Um LayaService por gateway (backend compartilhado do processo; pesos carregados sob demanda)."""
    svc = getattr(gw, "_laya_service", None)
    if svc is None:
        review = getattr(getattr(gw, "jev_cfg", None), "review_action", "keep")
        svc = LayaService(LayaConfig(), get_backend(), review_action=review)
        try:
            gw._laya_service = svc
        except AttributeError:
            pass
    return svc


def _safety_net(judged_in: list[Candidate], survivors: list[Candidate], rc, max_results: int) -> tuple[list[Candidate], int]:
    """Mesma regra do graphify_jev (§25): nunca devolver contexto vazio; nunca sobrepõe QUARANTINE."""
    if survivors or not judged_in:
        return survivors, 0
    safe = [c for c in judged_in if c.decision != QUARANTINE]
    fb = sorted(safe, key=lambda c: -c.score)[:min(rc.jev_min_survivors, max_results)]
    for c in fb:
        c.decision = f"{c.decision}_FALLBACK" if c.decision else "FALLBACK"
    return fb, len(fb)


def _common_metrics(metrics: dict, lm: LayaMetrics, judged_in, survivors, full, t_filter0, t_filter1, t2, fb_used):
    metrics.update(lm.to_dict())
    metrics.update({
        "filter_latency_ms": round(metrics.pop("dedup_latency_ms") + (t_filter1 - t_filter0) * 1000, 1),
        "full_note_latency_ms": round((t2 - t_filter1) * 1000, 1),
        "documents_sent_to_laya": len(judged_in),
        "documents_kept": lm.kept, "documents_review": lm.review, "documents_dropped": lm.dropped,
        "documents_quarantined": lm.quarantined, "documents_unjudged": lm.unjudged,
        "jev_fallback_used": fb_used,   # mesma chave de saúde do juiz: contexto de segurança foi usado
        "survivor_tokens_snippets": _tokens(survivors),
    })


def run_graphify_laya(gw, query: str, max_results: int, jev=None):
    uniq, metrics = _graphify_candidates(gw, query, allow_ppr=False)
    rc = gw.retrieval_cfg
    judged_in, withheld, pf = prefilter(query, uniq, rc.prefilter_top_k, rc.prefilter_lexical_weight)
    metrics.update(pf)
    svc = laya_service(gw)
    t0 = time.perf_counter()
    survivors, lm = svc.evaluate(query, judged_in)
    t1 = time.perf_counter()
    survivors = sorted(survivors, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]
    survivors, fb = _safety_net(judged_in, survivors, rc, max_results)
    full = {c.candidate_id: full_note_text(gw, c) for c in survivors}
    t2 = time.perf_counter()
    _common_metrics(metrics, lm, judged_in, survivors, full, t0, t1, t2, fb)
    metrics["_all_candidates"] = judged_in + withheld
    return survivors, full, metrics


def decision_engine(gw):
    """ANAM-043: um DecisionEngine por gateway, REUTILIZANDO o LayaService e o JEV do próprio gateway
    (mesmo backend, mesmos pesos, mesmo cache de JEV). Config: MG_DECISION_* (padrão = JEV-only)."""
    from app.decision import DecisionEngine
    eng = getattr(gw, "_decision_engine", None)
    if eng is None:
        eng = DecisionEngine(jev=getattr(gw, "jev", None), laya_service=laya_service(gw))
        try:
            gw._decision_engine = eng
        except AttributeError:
            pass
    return eng


def run_graphify_decision(gw, query: str, max_results: int, jev=None):
    """graphify -> prefilter -> DecisionEngine (provider/estratégia/preset por config) -> sobreviventes.

    NÃO registrado em PIPELINES de propósito (a lista é contrato de UI/CLI/MCP/benchmark e `graphify_jev_opt`
    permanece o padrão); chamável por código/bench e pelo /api/decision. Fallback do Engine para retrieval:
    candidatos passam SINALIZADOS (`decision_fallback=1`), nunca descartados em silêncio.
    """
    from app.decision import DecisionRequest, Item
    uniq, metrics = _graphify_candidates(gw, query, allow_ppr=False)
    rc = gw.retrieval_cfg
    judged_in, withheld, pf = prefilter(query, uniq, rc.prefilter_top_k, rc.prefilter_lexical_weight)
    metrics.update(pf)
    eng = decision_engine(gw)
    if jev is not None:
        eng.bind_jev(jev)
    t0 = time.perf_counter()
    res = eng.decide(DecisionRequest(query, [Item(c.candidate_id, c.snippet or "", c.source_file, c.section)
                                             for c in judged_in], project=getattr(gw, "project", "") or ""))
    t1 = time.perf_counter()
    review = eng.cfg.review_action
    survivors = []
    for c, d in zip(judged_in, res.items):
        c.decision, c.relevance = d.decision, d.score
        c.meta["decision"] = d.to_public()
        if d.survives(review):
            survivors.append(c)
    survivors = sorted(survivors, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]
    survivors, fb = _safety_net(judged_in, survivors, rc, max_results)
    full = {c.candidate_id: full_note_text(gw, c) for c in survivors}
    metrics.update({"decision_provider": res.provider, "decision_strategy": res.strategy,
                    "decision_latency_ms": round(res.latency_ms, 1), "decision_fallbacks": res.fallback_count,
                    "decision_jev_items": res.jev_items, "decision_jev_calls_avoided": res.jev_calls_avoided,
                    "decision_cache_hits": res.cache_hits, "documents_sent_to_decision": len(judged_in),
                    "filter_latency_ms": round((t1 - t0) * 1000, 1), "survivor_tokens_snippets": _tokens(survivors),
                    "jev_fallback_used": fb, "_all_candidates": judged_in + withheld})
    return survivors, full, metrics


def run_graphify_laya_jev(gw, query: str, max_results: int, jev=None):
    """Cascata: Laya filtra barato; JEV só nos incertos / suspeitos."""
    uniq, metrics = _graphify_candidates(gw, query, allow_ppr=False)
    rc = gw.retrieval_cfg
    jev = jev or gw.jev
    judged_in, withheld, pf = prefilter(query, uniq, rc.prefilter_top_k, rc.prefilter_lexical_weight)
    metrics.update(pf)
    svc = laya_service(gw)
    cfg = svc.cfg
    t0 = time.perf_counter()
    answers, lm = svc.score(query, judged_in)

    settled: list[Candidate] = []     # decididos só pelo Laya
    escalate: list[Candidate] = []    # vão ao JEV
    for c, a in zip(judged_in, answers):
        if a is None:                 # Laya indisponível -> JEV decide tudo (fallback explícito, ver cabeçalho)
            escalate.append(c)
            continue
        c.relevance = round(a.p_yes, 4)
        c.meta["laya"] = a.to_dict()
        b = band(a.p_yes, cfg)
        confident = a.confidence >= cfg.min_confidence
        if b == DROP and confident:
            c.decision = DROP
            lm.dropped += 1
        elif b == KEEP and confident and not screen(c.snippet or "").suspicious:
            c.decision = KEEP
            lm.kept += 1
            settled.append(c)
        else:
            escalate.append(c)
    lm.escalated = len(escalate)
    jm = None
    survivors = list(settled)
    if escalate:
        jsurv, jm = jev.evaluate(query, escalate)
        survivors += jsurv
    t1 = time.perf_counter()
    survivors = sorted(survivors, key=lambda c: (-(c.relevance or 0), -c.score))[:max_results]
    survivors, fb = _safety_net(judged_in, survivors, rc, max_results)
    full = {c.candidate_id: full_note_text(gw, c) for c in survivors}
    t2 = time.perf_counter()
    jd: dict[str, Any] = jm.to_dict() if jm is not None else {}
    _common_metrics(metrics, lm, judged_in, survivors, full, t0, t1, t2, fb)
    # os contadores finais por decisão vêm das decisões reais (Laya + JEV), não só do Laya
    metrics.update({
        "documents_kept": sum(1 for c in judged_in if c.decision == KEEP),
        "documents_review": sum(1 for c in judged_in if c.decision == REVIEW),
        "documents_dropped": sum(1 for c in judged_in if c.decision == DROP),
        "documents_quarantined": sum(1 for c in judged_in if c.decision == QUARANTINE),
        "documents_unjudged": sum(1 for c in judged_in if c.decision in (UNJUDGED, None)),
        "documents_sent_to_jev": len(escalate),
        "jev_latency_ms": jd.get("latency_ms", 0.0),
        "jev_input_tokens": jd.get("input_tokens", 0),
        "jev_output_tokens": jd.get("output_tokens", 0),
        "jev_cache_hits": jd.get("cache_hits", 0),
        "jev_cache_enabled": jd.get("cache_enabled"),
        "jev": jd,
        "_all_candidates": judged_in + withheld,
    })
    return survivors, full, metrics


register_pipeline("graphify_laya", run_graphify_laya)
register_pipeline("graphify_laya_jev", run_graphify_laya_jev)
