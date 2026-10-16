"""Contrato `DecisionProvider` (ANAM-043)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.decision.types import DecisionRequest, DecisionResult


class DecisionProvider(ABC):
    """Um decisor. `decide` recebe UMA requisição (query + N itens) e devolve uma decisão por item.

    Se o provider não puder decidir (indisponível/operação não suportada) levanta `ProviderUnavailable`;
    quem aplica o fallback por tipo de operação é o `DecisionEngine` (nunca o provider, nunca em silêncio).
    `health()` não faz chamada de rede/modelo: reporta o que se sabe sem pagar nem carregar pesos.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Versão do prompt/lógica do provider (entra na chave de cache)."""

    @property
    def checkpoint(self) -> str:
        """Identificador do modelo/pesos em uso (entra na chave de cache)."""
        return ""

    @abstractmethod
    def capabilities(self) -> dict: ...

    @abstractmethod
    def health(self) -> dict: ...

    @abstractmethod
    def decide(self, request: DecisionRequest) -> DecisionResult: ...

    def batch(self, requests: list[DecisionRequest]) -> list[DecisionResult]:
        return [self.decide(r) for r in requests]
