"""DecisionEngine: orquestra provider + cache + fallback por tipo de operação + telemetria (ANAM-043).

Padrão do produto continua JEV-only (`graphify_jev_opt`); Laya/híbridos/adaptive são opt-in
(`MG_DECISION_PROVIDER` / preset). Os dados mediram que Laya NÃO supera o baseline lexical em relevância neste
corpus sintético (docs/bench/anam-042-laya.md); portanto nenhuma configuração aqui é recomendada por padrão.

Fallback por operação (aplicado AQUI, nunca silencioso; o item sai com fallback=True):
  retrieval  -> passa (decision=UNJUDGED, fallback_action=allow)      [contexto > perda por indisponibilidade]
  memory     -> REVIEW (fallback_action=review)                      [humano/regra decide; nunca grava sozinho]
  security   -> QUARANTINE (fallback_action=block)                   [fail-closed]
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import replace
from typing import Any

from app.decision.base import DecisionProvider
from app.decision.cache import DecisionCache, cache_key
from app.decision.config import DEFAULT_PROVIDER, FALLBACK_POLICY, PROVIDERS, DecisionConfig, load_config
from app.decision.hybrid import AdaptiveDecisionProvider, HybridDecisionProvider
from app.decision.providers import JEVDecisionProvider, LayaDecisionProvider
from app.decision.telemetry import DecisionHistory, build_record, default_history_path
from app.decision.types import (MAX_BATCH, MAX_ITEMS, MAX_TEXT_CHARS, MEASURED, OP_MEMORY, OP_RETRIEVAL, OP_SECURITY,
                                QUARANTINE, REVIEW, UNJUDGED, UNKNOWN, DecisionRequest, DecisionResult,
                                ItemDecision, ProviderUnavailable, labeled)
from app.services.metrics import redact

SLUG = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
FALLBACK = {OP_RETRIEVAL: (UNJUDGED, "allow"), OP_MEMORY: (REVIEW, "review"), OP_SECURITY: (QUARANTINE, "block")}


def validate_request(req: DecisionRequest) -> DecisionRequest:
    req.validate()
    if req.project and not SLUG.match(req.project):
        raise ValueError("project inválido (A-Z a-z 0-9 _ . -, até 64)")
    if not req.items:
        raise ValueError("items vazio")
    if len(req.items) > MAX_ITEMS:
        raise ValueError(f"máx. {MAX_ITEMS} itens por requisição")
    if len({i.candidate_id for i in req.items}) != len(req.items):
        raise ValueError("candidate_id duplicado")
    if any(len(i.text) > MAX_TEXT_CHARS for i in req.items):
        raise ValueError(f"texto > {MAX_TEXT_CHARS} chars")
    return req


def fallback_item(op: str, candidate_id: str, content_hash: str, why: str, provider: str) -> ItemDecision:
    decision, action = FALLBACK[op]
    return ItemDecision(candidate_id, content_hash, decision, provider=provider, reason=why[:160],
                        fallback=True, fallback_action=action)


class DecisionEngine:
    def __init__(self, cfg: DecisionConfig | None = None, *, jev: Any | None = None, laya_service: Any | None = None,
                 history: DecisionHistory | None = None):
        self.cfg = (cfg or load_config()).validate()
        self.jev_provider = JEVDecisionProvider(self.cfg, jev=jev)
        self.laya_provider = LayaDecisionProvider(self.cfg, service=laya_service)
        # Colibri (IA local por API, ANAM-041/046): JEV-decision com backend loopback MG_COLIBRI_URL, custo 0.
        # A fábrica levanta indisponibilidade explícita quando MG_COLIBRI_ENABLED=off ou servidor fora do ar.
        from app.services.colibri import colibri_provider_factory, colibri_status
        self.colibri_provider = JEVDecisionProvider(self.cfg, jev_factory=colibri_provider_factory(),
                                                    label="colibri", name="colibri", health_fn=colibri_status)
        self.providers: dict[str, DecisionProvider] = {
            "jev": self.jev_provider, "laya": self.laya_provider, "colibri": self.colibri_provider,
            "hybrid": HybridDecisionProvider(self.cfg, self.jev_provider, self.laya_provider),
            "adaptive": AdaptiveDecisionProvider(self.cfg, self.jev_provider, self.laya_provider)}
        self.cache = DecisionCache(self.cfg.cache_size)
        self.history = history or DecisionHistory(self.cfg.history_size, default_history_path(), self.cfg.history_persist)
        self._lock = threading.Lock()

    # -- composição -----------------------------------------------------------------------------
    def bind_jev(self, jev: Any) -> None:
        if jev is not None:
            self.jev_provider.bind(jev)

    def provider(self, name: str) -> DecisionProvider:
        if name not in self.providers:
            raise ValueError(f"provider inválido: {name!r} ({'|'.join(PROVIDERS)})")
        return self.providers[name]

    # -- decisão --------------------------------------------------------------------------------
    def decide(self, req: DecisionRequest, *, provider: str | None = None, strategy: str | None = None,
               record: bool = True) -> DecisionResult:
        validate_request(req)
        pname, pstrat = self.cfg.provider_for(req.project)
        pname, pstrat = provider or pname, strategy or pstrat
        prov = self.provider(pname)
        t0 = time.perf_counter()
        policy = self.cfg.policy_hash(req.project) + (f":{pstrat}" if pname == "hybrid" else "")
        keys = {}
        for it in req.items:
            keys[it.candidate_id] = cache_key(op=req.op, project=req.project, provider=pname, strategy=pstrat,
                                              query=req.query, content_hash=it.content_hash, schema=req.schema,
                                              checkpoint=prov.checkpoint, version=prov.version, policy=policy)
        hits = {cid: self.cache.get(k) for cid, k in keys.items()}
        todo = [it for it in req.items if hits[it.candidate_id] is None]
        res = DecisionResult(req.request_id, req.op, pname, strategy=pstrat if pname == "hybrid" else "", project=req.project,
                             model=str(prov.checkpoint or ""))
        fresh: dict[str, ItemDecision] = {}
        if todo:
            sub = DecisionRequest(req.query, todo, req.op, req.project, req.schema, req.request_id)
            try:
                r = prov.decide(sub, strategy=pstrat) if isinstance(prov, HybridDecisionProvider) else prov.decide(sub)
                if len(r.items) != len(todo):
                    raise ProviderUnavailable("provider devolveu número de itens diferente do pedido")
                fresh = {d.candidate_id: d for d in r.items}
                res.calls, res.errors, res.jev_requests, res.strategy = r.calls, r.errors, r.jev_requests, r.strategy or res.strategy
            except Exception as exc:  # noqa: BLE001 — QUALQUER falha vira fallback explícito do tipo de operação
                why = redact(f"{pname} indisponível: {type(exc).__name__}: {exc}")  # Fase 7: erro de credencial nunca vaza a chave
                res.errors.append(why[:200])
                fresh = {it.candidate_id: fallback_item(req.op, it.candidate_id, it.content_hash, why, pname) for it in todo}
            for it in todo:  # item não julgado individualmente (UNJUDGED sem flag) também recebe fallback explícito
                d = fresh.get(it.candidate_id)
                if d is None or (d.decision == UNJUDGED and not d.fallback):
                    fresh[it.candidate_id] = fallback_item(req.op, it.candidate_id, it.content_hash,
                                                           d.reason if d and d.reason else "sem decisão", pname)
                else:
                    self.cache.put(keys[it.candidate_id], d)
        for it in req.items:
            d = hits[it.candidate_id] or fresh[it.candidate_id]
            res.items.append(d)
        res.cache_hits = sum(1 for v in hits.values() if v is not None)
        res.latency_ms = (time.perf_counter() - t0) * 1000
        if record:
            self.history.add(build_record(req, res))
        return res

    def batch(self, reqs: list[DecisionRequest], **kw) -> list[DecisionResult]:
        if len(reqs) > MAX_BATCH:
            raise ValueError(f"máx. {MAX_BATCH} requisições por batch")
        return [self.decide(r, **kw) for r in reqs]

    # -- leitura --------------------------------------------------------------------------------
    def status(self) -> dict:
        pname, pstrat = self.cfg.provider_for("")
        return {
            "version": "decision-engine-v1", "stage": "EXPERIMENTAL",
            "active_provider": pname, "active_strategy": pstrat if pname == "hybrid" else None,
            "default_pipeline": "graphify_jev_opt", "default_is_jev_only": pname == DEFAULT_PROVIDER,
            "providers": {n: p.health() for n, p in self.providers.items() if n in ("jev", "laya", "colibri")},
            "capabilities": {n: p.capabilities() for n, p in self.providers.items()},
            "cache": self.cache.stats(), "history": {"records": self.history.total, "persist": self.history.persist},
            "fallback_policy": FALLBACK_POLICY,
            "measurements": {
                "laya_vs_lexical": labeled("AUC 0,64–0,68 vs 0,975", MEASURED, "docs/bench/anam-042-laya.md (corpus sintético)"),
                "jev_real": labeled(None, UNKNOWN, "JEV real (TypeSafe): não medido"),
                "decision_bench": "docs/bench/decision-engine.md"},
            "labels": {"MEASURED": "medido nesta máquina/dados", "ESTIMATED": "modelo/extrapolação", "UNKNOWN": "não medido"},
        }

    def evaluation(self) -> dict:
        import json

        from config.paths import PACKAGE_ROOT
        out = {"history": self.history.metrics().get("divergence") or {"note": "histórico vazio (nada medido ainda)"}, "bench": None}
        p = PACKAGE_ROOT / "docs" / "bench" / "decision-engine.json"
        if p.exists():
            try:
                out["bench"] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out["bench"] = {"error": "decision-engine.json ilegível"}
        else:
            out["bench_note"] = "rode scripts/bench_decision.py"
        return out


_ENGINE: DecisionEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> DecisionEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = DecisionEngine()
        return _ENGINE


def reset_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
