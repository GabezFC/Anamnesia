"""Tipos do Anamnésia Decision Engine (ANAM-043). Sem I/O, sem texto privado em estruturas de telemetria.

Vocabulário de decisão = o do JEV/Laya (KEEP/REVIEW/DROP/QUARANTINE/UNJUDGED). Operações:
  retrieval  relevância de candidatos de recuperação (fallback: permitido, SINALIZADO)
  memory     triagem de escrita de memória            (fallback: REVIEW)
  security   sensibilidade/injeção                     (fallback: fail-closed = QUARANTINE)
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

KEEP, REVIEW, DROP, QUARANTINE, UNJUDGED = "KEEP", "REVIEW", "DROP", "QUARANTINE", "UNJUDGED"
DECISIONS = (KEEP, REVIEW, DROP, QUARANTINE, UNJUDGED)

OP_RETRIEVAL, OP_MEMORY, OP_SECURITY = "retrieval", "memory", "security"
OPS = (OP_RETRIEVAL, OP_MEMORY, OP_SECURITY)

# Rótulos de proveniência de cada número reportado.
MEASURED, ESTIMATED, UNKNOWN = "MEASURED", "ESTIMATED", "UNKNOWN"
LABELS = (MEASURED, ESTIMATED, UNKNOWN)

MAX_ITEMS = 50          # itens por requisição (REST)
MAX_TEXT_CHARS = 4000   # texto por item (REST)
MAX_BATCH = 20          # requisições por /batch


class ProviderUnavailable(RuntimeError):
    """O provider não pôde decidir (indisponível/não suporta a operação). O Engine aplica o fallback do tipo."""


def sha(text: str, n: int = 16) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:n]


def labeled(value: Any, label: str, source: str = "") -> dict:
    """Número com rótulo de proveniência. `value=None` força UNKNOWN."""
    if value is None:
        label = UNKNOWN
    out = {"value": value, "label": label}
    if source:
        out["source"] = source
    return out


@dataclass(frozen=True)
class Item:
    candidate_id: str
    text: str
    source: str = ""
    section: str = ""

    @property
    def content_hash(self) -> str:
        return sha(self.text)


@dataclass
class DecisionRequest:
    query: str
    items: list[Item]
    op: str = OP_RETRIEVAL
    project: str = ""          # isolamento: limiares/cache/histórico são por projeto
    schema: str = "relevance-v1"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def validate(self) -> "DecisionRequest":
        if self.op not in OPS:
            raise ValueError(f"op inválida: {self.op!r} ({'|'.join(OPS)})")
        return self


@dataclass
class ItemDecision:
    candidate_id: str
    content_hash: str
    decision: str
    score: float | None = None
    confidence: float | None = None
    provider: str = ""
    reason: str = ""
    fallback: bool = False           # True => o Engine/provedor degradou; nunca silencioso
    fallback_action: str = ""        # allow | review | block
    cached: bool = False
    escalated: bool = False          # passou pelo 2º provider (híbridos)
    others: dict = field(default_factory=dict)   # {provider: {"decision", "score", "confidence"}} p/ divergência

    def survives(self, review_action: str = "keep") -> bool:
        if self.fallback and self.fallback_action == "allow":
            return True
        return self.decision == KEEP or (self.decision == REVIEW and review_action == "keep")

    def to_public(self) -> dict:
        """Forma segura para REST/MCP: IDs e hashes, nunca o texto."""
        return {"candidate_id": self.candidate_id, "content_hash": self.content_hash, "decision": self.decision,
                "score": None if self.score is None else round(self.score, 4),
                "confidence": None if self.confidence is None else round(self.confidence, 4),
                "provider": self.provider, "reason": self.reason, "fallback": self.fallback,
                "fallback_action": self.fallback_action, "cached": self.cached, "escalated": self.escalated,
                "others": self.others}


@dataclass
class DecisionResult:
    request_id: str
    op: str
    provider: str
    strategy: str = ""
    project: str = ""
    items: list[ItemDecision] = field(default_factory=list)
    latency_ms: float = 0.0
    calls: dict = field(default_factory=dict)       # {provider: itens avaliados}
    jev_requests: int = 0
    errors: list[str] = field(default_factory=list)
    cache_hits: int = 0

    @property
    def fallback_count(self) -> int:
        return sum(1 for i in self.items if i.fallback)

    @property
    def jev_items(self) -> int:
        return int(self.calls.get("jev", 0))

    @property
    def jev_calls_avoided(self) -> int:
        """Itens que um JEV-only teria enviado ao JEV e esta decisão não enviou (contagem: MEASURED)."""
        return max(0, len(self.items) - self.jev_items - sum(1 for i in self.items if i.cached))

    def to_public(self) -> dict:
        from app.decision.cost import estimate_jev_tokens
        return {"request_id": self.request_id, "op": self.op, "provider": self.provider, "strategy": self.strategy,
                "project": self.project, "items": [i.to_public() for i in self.items],
                "latency_ms": labeled(round(self.latency_ms, 2), MEASURED),
                "calls": self.calls, "jev_calls": labeled(self.jev_items, MEASURED),
                "jev_calls_avoided": labeled(self.jev_calls_avoided, MEASURED),
                "jev_tokens": labeled(estimate_jev_tokens(self.jev_requests, self.jev_items), ESTIMATED,
                                      "340*requests+209*questions (app/services/jev.py)"),
                "jev_cost_usd": labeled(None, UNKNOWN, "JEV real: não medido"),
                "cache_hits": self.cache_hits, "fallback_count": self.fallback_count, "errors": self.errors[:5]}
