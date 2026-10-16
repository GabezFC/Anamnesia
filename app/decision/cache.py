"""Cache de decisões em memória (LRU, thread-safe). A chave NUNCA contém texto: só hashes.

Chave = SHA-256 de: operação, projeto, provider, estratégia, hash(query), hash do candidato, schema, checkpoint do
modelo, versão do provider e hash da política (limiares/pesos/fallback). Qualquer mudança em algum desses
campos invalida a entrada sem precisar limpar o cache. Decisões de fallback/UNJUDGED nunca são armazenadas.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import replace

from app.decision.types import UNJUDGED, ItemDecision, sha


def cache_key(*, op: str, project: str, provider: str, strategy: str, query: str, content_hash: str, schema: str,
              checkpoint: str, version: str, policy: str) -> str:
    parts = (op, project, provider, strategy, sha(query, 32), content_hash, schema, checkpoint, version, policy)
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class DecisionCache:
    def __init__(self, max_size: int = 2048):
        self.max_size = max(0, int(max_size))
        self._d: OrderedDict[str, ItemDecision] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = self.misses = self.stores = 0

    @property
    def enabled(self) -> bool:
        return self.max_size > 0

    def get(self, key: str) -> ItemDecision | None:
        if not self.enabled:
            return None
        with self._lock:
            v = self._d.get(key)
            if v is None:
                self.misses += 1
                return None
            self._d.move_to_end(key)
            self.hits += 1
            return replace(v, cached=True)

    def put(self, key: str, d: ItemDecision) -> bool:
        if not self.enabled or d.fallback or d.decision == UNJUDGED:
            return False
        with self._lock:
            self._d[key] = replace(d, cached=False)
            self._d.move_to_end(key)
            self.stores += 1
            while len(self._d) > self.max_size:
                self._d.popitem(last=False)
        return True

    def clear(self) -> None:
        with self._lock:
            self._d.clear()

    def stats(self) -> dict:
        with self._lock:
            n = self.hits + self.misses
            return {"enabled": self.enabled, "size": len(self._d), "max_size": self.max_size, "hits": self.hits,
                    "misses": self.misses, "stores": self.stores,
                    "hit_rate": round(self.hits / n, 4) if n else None}
