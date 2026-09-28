"""Layered, versioned judgement cache (§11, §15, §22, §23, §16).

THE PROBLEM WITH THE OLD CACHE
------------------------------
Measured 2026-09-27: 0 hits across 204 recorded runs. Two independent causes:
  1. the raw query string was part of the key, so any rewording forked it;
  2. every entry mixed judgement identity with pipeline identity, so nothing could be invalidated
     selectively — the only safe move was to distrust the whole cache.

DESIGN
------
One row = one judgement of one (query-representation, candidate-content) pair under one explicit
version vector. Three query layers of decreasing safety, looked up in order:

  L1 exact        canonical query (accents/case/punctuation/stop-words normalized, ORDER KEPT)
  L2 normalized   sorted unique terms (order- and repetition-independent)
  L3 fingerprint  sorted unique STEMMED terms  -- LOOSEST, shadow mode by default

L1 and L2 cannot change the meaning of a query; L3 can ("licença do Redis" vs "licenças de
software"), so L3 is served only when `promote_l3` is on, and otherwise recorded as a *suggestion*
so its false-positive rate can be measured against the real judgement before anyone trusts it (§12).

Two more layers avoid recomputation rather than judgement:
  L4 ranking      query-representation -> ordered candidate ids (skips BM25 + graph + hybrid rank)
  L5 snippet      (content_hash, policy_version, budget) -> extracted snippet

VERSIONING (§16, §23)
---------------------
Every row carries the full version vector: jev model, prompt version, jev mode, thresholds, ranking
version, snippet policy version, query-normalizer version, candidate content hash. The vector is
hashed into the key, so changing ANY of them cannot produce a stale hit — the old row simply stops
being addressable (and is prunable by `purge_stale`). A judgement produced under different settings
is never compared to one produced under the current settings.

NEGATIVE CACHE (§22)
--------------------
DROP verdicts are the overwhelming majority (94.9% measured) and are cached exactly like the others
— there is no separate negative store, because a separate store would need its own invalidation and
would drift. What IS separate is the metric: `negative_hits` counts the hits that avoided re-judging
something already known to be irrelevant, which is where most of the savings come from.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.services.query_fp import QUERY_NORMALIZER_VERSION, canonical, fingerprint, term_key

CACHE_SCHEMA_VERSION = "cache-v2"
RANKING_VERSION = "rank-v1"

L1, L2, L3, L4, L5 = "l1_exact", "l2_normalized", "l3_fingerprint", "l4_ranking", "l5_snippet"


@dataclass(frozen=True)
class CacheIdentity:
    """Everything that can change a judgement. All of it goes into the key (§16).

    `namespace` is not a property of the judgement — it is an isolation handle. A benchmark run sets
    it so its arms cannot read judgements cached by a previous run: measured 2026-09-27, an earlier
    smoke run left entries that made the BASELINE arm report zero judge tokens on 3 of 5 questions and
    "win" by 2x. Production leaves it empty and amortizes normally.
    """
    model: str
    prompt_version: str
    jev_mode: str
    relevance_threshold: float
    review_threshold: float
    ranking_version: str = RANKING_VERSION
    snippet_policy_version: str = ""
    query_normalizer_version: str = QUERY_NORMALIZER_VERSION
    cache_schema_version: str = CACHE_SCHEMA_VERSION
    namespace: str = ""

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


def _key(layer: str, qrepr: Any, content_hash: str, ident: CacheIdentity, extra: Any = None) -> str:
    raw = json.dumps([layer, qrepr, content_hash, ident.digest(), extra], sort_keys=True,
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class CacheStats:
    lookups: int = 0
    hits_l1: int = 0
    hits_l2: int = 0
    hits_l3: int = 0
    hits_l4: int = 0
    hits_l5: int = 0
    misses: int = 0
    writes: int = 0
    negative_hits: int = 0       # hits whose cached verdict was a DROP-range relevance
    l3_suggested: int = 0        # shadow mode: L3 would have hit but was not served
    l3_agreements: int = 0       # shadow: suggestion matched the real judgement's routing band
    l3_disagreements: int = 0    # shadow: suggestion would have changed the routing band
    l3_abs_error: list[float] = field(default_factory=list)

    @property
    def hits(self) -> int:
        return self.hits_l1 + self.hits_l2 + self.hits_l3

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "l3_abs_error"}
        d["hits"] = self.hits
        d["hit_rate"] = round(self.hits / self.lookups, 4) if self.lookups else None
        errs = self.l3_abs_error
        d["l3_mean_abs_error"] = round(sum(errs) / len(errs), 4) if errs else None
        d["l3_max_abs_error"] = round(max(errs), 4) if errs else None
        d["l3_false_positive_rate"] = (
            round(self.l3_disagreements / (self.l3_agreements + self.l3_disagreements), 4)
            if (self.l3_agreements + self.l3_disagreements) else None)
        return d


class LayeredCache:
    """Query-representation-aware cache over a simple key/value store.

    `get`/`put` are injected (the SQLite store in app/database/db.py, or a dict in tests), so this
    class owns identity and layering only — never storage.
    """

    def __init__(self, get: Callable[[str], dict | None] | None,
                 put: Callable[[str, dict], None] | None,
                 ident: CacheIdentity, *, promote_l3: bool = False,
                 enable_l2: bool = True, enable_l3_shadow: bool = True):
        self._get, self._put = get, put
        self.ident = ident
        self.promote_l3 = promote_l3
        self.enable_l2 = enable_l2
        self.enable_l3_shadow = enable_l3_shadow
        self.stats = CacheStats()
        # Pending shadow comparisons: key -> (suggested_relevance, candidate_id)
        self._shadow: dict[str, tuple[float, str]] = {}

    @property
    def enabled(self) -> bool:
        return self._get is not None

    # -- judgement layers ----------------------------------------------------
    def get_judgement(self, query: str, content_hash: str) -> tuple[dict | None, str | None]:
        """Look up a judgement. Returns (value, layer_hit) — value is None on a miss."""
        if self._get is None:
            return None, None
        self.stats.lookups += 1
        reprs = [(L1, canonical(query), "hits_l1")]
        if self.enable_l2:
            reprs.append((L2, list(term_key(query)), "hits_l2"))
        for layer, qr, counter in reprs:
            v = self._get(_key(layer, qr, content_hash, self.ident))
            if v:
                setattr(self.stats, counter, getattr(self.stats, counter) + 1)
                self._count_negative(v)
                return v, layer

        fp_key = _key(L3, list(fingerprint(query)), content_hash, self.ident)
        v3 = self._get(fp_key) if (self.promote_l3 or self.enable_l3_shadow) else None
        if v3 and self.promote_l3:
            self.stats.hits_l3 += 1
            self._count_negative(v3)
            return v3, L3
        if v3 is not None and v3.get("relevance") is not None:
            # SHADOW MODE (§12/§33): record what L3 would have returned, compare after the real
            # judgement arrives, and never serve it.
            self.stats.l3_suggested += 1
            self._shadow[content_hash] = (float(v3["relevance"]), fp_key)
        self.stats.misses += 1
        return None, None

    def put_judgement(self, query: str, content_hash: str, value: dict) -> None:
        """Write the judgement into every query layer at once.

        Writing all layers on every put is what makes the looser layers useful: a paraphrase only
        hits L2/L3 if some earlier wording already populated them.
        """
        if self._put is None:
            return
        payload = {**value, "cached_at": time.time(), "identity": self.ident.digest()}
        self._put(_key(L1, canonical(query), content_hash, self.ident), payload)
        if self.enable_l2:
            self._put(_key(L2, list(term_key(query)), content_hash, self.ident), payload)
        self._put(_key(L3, list(fingerprint(query)), content_hash, self.ident), payload)
        self.stats.writes += 1

    def record_shadow_outcome(self, content_hash: str, real_relevance: float | None,
                              band: Callable[[float], str]) -> None:
        """Compare a pending L3 suggestion with the judgement that actually came back."""
        pending = self._shadow.pop(content_hash, None)
        if pending is None or real_relevance is None:
            return
        suggested, _ = pending
        self.stats.l3_abs_error.append(abs(suggested - real_relevance))
        if band(suggested) == band(real_relevance):
            self.stats.l3_agreements += 1
        else:
            self.stats.l3_disagreements += 1

    def _count_negative(self, v: dict) -> None:
        r = v.get("relevance")
        if r is not None and r < self.ident.review_threshold:
            self.stats.negative_hits += 1

    # -- L4: ranking ---------------------------------------------------------
    def get_ranking(self, query: str, corpus_version: str) -> list[str] | None:
        if self._get is None:
            return None
        v = self._get(_key(L4, list(term_key(query)), corpus_version, self.ident))
        if v and isinstance(v.get("order"), list):
            self.stats.hits_l4 += 1
            return v["order"]
        return None

    def put_ranking(self, query: str, corpus_version: str, order: list[str]) -> None:
        if self._put is None:
            return
        self._put(_key(L4, list(term_key(query)), corpus_version, self.ident),
                  {"order": order, "cached_at": time.time()})

    # -- L5: snippets --------------------------------------------------------
    def get_snippet(self, content_hash: str, policy: str, budget: int, qkey: Any) -> str | None:
        if self._get is None:
            return None
        v = self._get(_key(L5, [policy, budget, qkey], content_hash, self.ident))
        if v and isinstance(v.get("snippet"), str):
            self.stats.hits_l5 += 1
            return v["snippet"]
        return None

    def put_snippet(self, content_hash: str, policy: str, budget: int, qkey: Any, snippet: str) -> None:
        if self._put is None:
            return
        self._put(_key(L5, [policy, budget, qkey], content_hash, self.ident),
                  {"snippet": snippet, "cached_at": time.time()})
