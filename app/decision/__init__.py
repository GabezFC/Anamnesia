"""Anamnésia Decision Engine (ANAM-043): decisão KEEP/REVIEW/DROP/QUARANTINE com providers intercambiáveis.

Imports leves: nada aqui carrega torch/laya; o provider Laya só toca o backend ao decidir.
"""
from app.decision.base import DecisionProvider
from app.decision.config import DecisionConfig, load_config
from app.decision.engine import DecisionEngine, get_engine, reset_engine
from app.decision.hybrid import AdaptiveDecisionProvider, HybridDecisionProvider
from app.decision.providers import JEVDecisionProvider, LayaDecisionProvider
from app.decision.types import DecisionRequest, DecisionResult, Item, ItemDecision, ProviderUnavailable

__all__ = ["DecisionProvider", "DecisionConfig", "load_config", "DecisionEngine", "get_engine", "reset_engine",
           "AdaptiveDecisionProvider", "HybridDecisionProvider", "JEVDecisionProvider", "LayaDecisionProvider",
           "DecisionRequest", "DecisionResult", "Item", "ItemDecision", "ProviderUnavailable"]
