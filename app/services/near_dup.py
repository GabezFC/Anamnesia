"""Near-duplicate detection and clustering before the paid judge (§10, zero tokens, zero network).

WHY
---
`app/services/dedup.py` already removes EXACT duplicates (identical normalized content hash) and
caps candidates per note. It cannot see the expensive case: two different notes whose content is
95% the same — a copy under another filename, an older version of a decision, a note duplicated
during a vault reorganisation. Those arrive as distinct candidates with distinct content hashes and
the judge pays full price to reach the same verdict on each of them.

APPROACH (two cheap stages, both deterministic)
-----------------------------------------------
1. SimHash (64-bit, token-frequency weighted) gives every candidate a fingerprint whose Hamming
   distance approximates cosine similarity. Candidates are bucketed by banded fingerprint prefixes
   so we only compare plausible pairs instead of all N².
2. Every surviving pair is confirmed with a length-invariant SEQUENCE similarity over normalized
   token lists (difflib.SequenceMatcher). SimHash alone has false positives, so the reported
   similarity is a real measured number and not a hash artefact.

WHY SEQUENCE SIMILARITY AND NOT SHINGLE JACCARD (measured 2026-09-27)
--------------------------------------------------------------------
Fixed-k shingle Jaccard was tried first and rejected: it is strongly length-dependent and its set
semantics silently collapse repeated phrasing, which real notes are full of. On the same pair of
near-identical notes it produced 0.69 at 28 tokens but 0.80 at 196 tokens with the differing
sentence unchanged — so a single threshold could not mean the same thing for a short note and a long
one, and tuning it for one broke the other. Sequence similarity on the same pairs:

    pair                                   jaccard(k=4)   sequence ratio
    near-identical, short note                 0.6923          0.9600
    near-identical, long note                  0.8000          0.9925
    unrelated notes                            ~0.00           0.0417
    same sentences, paragraphs reordered        high            0.6000

It is length-invariant, still order-sensitive (a reordered note scores 0.60, correctly NOT a
duplicate), and it is the same metric the synthetic corpus generator uses to build its duplicate
groups — so the detector and the ground truth speak one language. Jaccard is retained as a cheap
pre-gate before the more expensive comparison.

WHY THIS RARELY FIRES IN THIS PIPELINE (measured 2026-09-27 — read before tuning it)
------------------------------------------------------------------------------------
On the 520-note synthetic corpus, whose manifest declares 60 duplicate groups, near-duplicate
clustering collapsed ZERO candidates at judge time across every measured query. The clusterer is not
at fault — in isolation it recovers 58 of the 60 groups with pair-precision 1.0000. The pipeline
simply never presents it with the opportunity:

  - `dedup.deduplicate(max_per_note=1)` runs FIRST and keeps one candidate per note, so two copies
    of a note can only co-occur as two DIFFERENT files;
  - the retriever seeds from BM25 over section bodies, and two near-identical notes compete for the
    same seed slots, so usually only the better-scoring one enters the pool at all;
  - measured directly: in 12 sampled queries, 2+ members of one declared duplicate group co-occurred
    in the candidate pool exactly ONCE (1/12), and after the per-note cap that single case still left
    nothing to merge.

So the honest expected value of this stage on THIS corpus is near zero, and it is kept enabled for
three specific reasons rather than out of optimism:
  1. it is free (deterministic, local, ~47 pair comparisons per query);
  2. its value scales with how duplicated the vault actually is — a real vault mid-reorganisation, or
     one with per-project copies of a shared decision, is exactly the case it was built for;
  3. it is the mechanism that makes the per-note cap SAFE to relax later: if `dedup_max_per_note` is
     ever raised (to deliver several sections of one long note), this stage is what stops the judge
     from paying for the same text twice.
Anyone tempted to report a saving from this stage must show `dedup_near_collapsed > 0` first.

SAFETY
------
Propagation is only sound if the members really are interchangeable, so the threshold is high by
default (0.92) and propagation is recorded per candidate (`meta["dup_of"]`) so any divergence can be
audited afterwards. A cluster never merges candidates from DIFFERENT notes at the default threshold
unless their bodies are genuinely near-identical — which is exactly the case we want to stop paying
for.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import zlib
from dataclasses import dataclass, field
from functools import lru_cache

from app.schemas.models import Candidate
from app.services.query_fp import fold
from config import env_bool

SIMHASH_BITS = 64
# Pairs compared with SequenceMatcher are truncated to this many tokens: the comparison is
# quadratic, and two notes that agree on their first 600 tokens are duplicates for our purposes.
_SEQ_MAX_TOKENS = 600
_WORD = re.compile(r"[a-z0-9][a-z0-9\-\.:_]*")


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(fold(text)) if len(t) >= 2]


def shingles(text: str, k: int = 4) -> set[str]:
    """Word k-shingles. Order-sensitive, so a reordered paragraph is NOT called identical."""
    ts = _tokens(text)
    if len(ts) < k:
        return {" ".join(ts)} if ts else set()
    return {" ".join(ts[i:i + k]) for i in range(len(ts) - k + 1)}


@lru_cache(maxsize=65536)
def _term_vector(term: str, bits: int) -> tuple[int, ...]:
    """+1/-1 por bit do hash estável do termo (blake2b; o hash() embutido é salgado por processo)."""
    h = int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=bits // 8).digest(), "big")
    return tuple(1 if (h >> i) & 1 else -1 for i in range(bits))


def simhash(text: str, bits: int = SIMHASH_BITS) -> int:
    """Charikar SimHash over token frequencies. Pure stdlib, stable across runs and machines.

    Python's builtin hash() is salted per process and must never be used here: the value ends up in
    cluster identity and (indirectly) in measurements, so it has to be reproducible.
    """
    ts = _tokens(text)
    if not ts:
        return 0
    weights = [0] * bits
    freq: dict[str, int] = {}
    for t in ts:
        freq[t] = freq.get(t, 0) + 1
    for term, w in freq.items():
        weights = [x + w * v for x, v in zip(weights, _term_vector(term, bits))]
    out = 0
    for i in range(bits):
        if weights[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def jaccard(a: set[str], b: set[str]) -> float:
    """Set overlap. Used only as a cheap pre-gate — see the module docstring for why it is not the
    arbiter."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def similarity(a: str, b: str) -> float:
    """Length-invariant, order-sensitive token-sequence similarity in [0,1]. The arbiter."""
    ta, tb = _tokens(a)[:_SEQ_MAX_TOKENS], _tokens(b)[:_SEQ_MAX_TOKENS]
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio()


@dataclass
class Cluster:
    """A group of near-identical candidates. `rep` is the one the judge actually sees."""
    rep: Candidate
    members: list[Candidate] = field(default_factory=list)   # excludes rep
    similarity: float = 1.0

    @property
    def size(self) -> int:
        return 1 + len(self.members)


class _UnionFind:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


# ANAM-017 (AUD-022): geração de pares por MinHash de partição única (OPH) sobre bigramas de palavras, em LSH
# com bandas de _LSH_ROWS bins. O SimHash de 64 bits + gate de Jaccard em 4-gramas só enxerga edições <= ~5%
# (detecção 55% a 8%, 10% a 12%, 0% a 20%); o OPH recupera os pares que o gerador antigo perdia.
# Custo O(shingles) por documento (um crc32 por bigrama), sem as 64 permutações do MinHash clássico.
_OPH_BINS = 32
_LSH_ROWS = 2
_LSH_MIN_EST = 0.15          # fração mínima de bins iguais (estima Jaccard de bigramas) para pagar o SequenceMatcher
_LSH_MAX_BUCKET = 64
NEAR_DUP_LSH_DEFAULT = True


def minhash_signature(text: str) -> list[int | None]:
    """One-permutation MinHash de bigramas: por bin (crc32 % bins) o menor valor; None = bin vazio."""
    ts = _tokens(text)
    bins: list[int | None] = [None] * _OPH_BINS
    for a, b in set(zip(ts, ts[1:])):
        h = zlib.crc32(f"{a} {b}".encode("utf-8"))
        k, v = h % _OPH_BINS, h // _OPH_BINS
        cur = bins[k]
        if cur is None or v < cur:
            bins[k] = v
    return bins


def _lsh_estimate(a: list[int | None], b: list[int | None]) -> float:
    both = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    return sum(1 for x, y in both if x == y) / len(both) if both else 0.0


def _bucket_pairs(buckets: dict) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for idxs in buckets.values():
        if len(idxs) < 2 or len(idxs) > _LSH_MAX_BUCKET:   # a huge bucket means the band carries no signal
            continue
        for a_pos in range(len(idxs)):
            for b_pos in range(a_pos + 1, len(idxs)):
                out.add((idxs[a_pos], idxs[b_pos]))        # idxs ascending => i < j
    return out


def _lsh_pairs(msigs: list[list[int | None]]) -> set[tuple[int, int]]:
    buckets: dict[tuple, list[int]] = {}
    for i, sig in enumerate(msigs):
        for band in range(_OPH_BINS // _LSH_ROWS):
            rows = sig[band * _LSH_ROWS:(band + 1) * _LSH_ROWS]
            if None in rows:
                continue
            buckets.setdefault((band, *rows), []).append(i)
    return _bucket_pairs(buckets)


def _simhash_pairs(sigs: list[int], bands: int) -> set[tuple[int, int]]:
    """Banded bucketing: split the 64-bit signature into `bands` chunks; only candidates sharing a chunk are
    compared. Two signatures within `hamming_max` bits differ in at most hamming_max positions, so with enough
    bands they almost certainly collide in at least one."""
    width = max(1, SIMHASH_BITS // max(1, bands))
    buckets: dict[tuple[int, int], list[int]] = {}
    for i, sig in enumerate(sigs):
        for b in range(bands):
            chunk = (sig >> (b * width)) & ((1 << width) - 1)
            buckets.setdefault((b, chunk), []).append(i)
    return _bucket_pairs(buckets)


def _confirm(i: int, j: int, texts: list[str], threshold: float,
             confirmed: dict[tuple[int, int], float], uf: "_UnionFind") -> None:
    sim = similarity(texts[i], texts[j])
    if sim >= threshold:
        confirmed[(i, j)] = sim
        uf.union(i, j)


def cluster_near_duplicates(cands: list[Candidate], threshold: float = 0.92,
                            hamming_max: int = 12, bands: int = 8,
                            lsh: bool | None = None) -> tuple[list[Cluster], dict]:
    """Group near-identical candidates. `cands` MUST already be in best-first order.

    Returns (clusters_in_input_order, metrics). The representative of each cluster is its
    best-ranked member, so clustering can never demote a candidate the ranker preferred.

    `lsh` (ANAM-017): adds MinHash/LSH candidate pairs to the SimHash ones. The arbiter is still
    `similarity() >= threshold`, so it only recovers duplicates the old generator missed; it never loosens
    what counts as a duplicate. None -> env MG_NEAR_DUP_LSH.
    """
    n = len(cands)
    if n <= 1:
        return [Cluster(rep=c) for c in cands], {
            "dedup_near_enabled": True, "dedup_near_in": n, "dedup_near_clusters": n,
            "dedup_near_collapsed": 0, "dedup_near_pairs_compared": 0,
        }

    use_lsh = env_bool("MG_NEAR_DUP_LSH", NEAR_DUP_LSH_DEFAULT) if lsh is None else lsh
    texts = [c.snippet or "" for c in cands]
    sigs = [simhash(t) for t in texts]
    shs = [shingles(t) for t in texts]
    sim_pairs = _simhash_pairs(sigs, bands)
    msigs = [minhash_signature(t) for t in texts] if use_lsh else []
    lsh_pairs = _lsh_pairs(msigs) if use_lsh else set()

    uf = _UnionFind(n)
    confirmed: dict[tuple[int, int], float] = {}
    # Jaccard pre-gate: deliberately far below `threshold`. Its only job is to reject pairs that are
    # nowhere near duplicates before paying for the sequence comparison; it must never be the reason
    # a real duplicate is missed, which is exactly what a tight Jaccard gate would cause.
    jaccard_gate = max(0.2, threshold - 0.35)
    for i, j in sim_pairs:
        if hamming(sigs[i], sigs[j]) <= hamming_max and jaccard(shs[i], shs[j]) >= jaccard_gate:
            _confirm(i, j, texts, threshold, confirmed, uf)
    for i, j in lsh_pairs - {k for k in confirmed}:
        if _lsh_estimate(msigs[i], msigs[j]) >= _LSH_MIN_EST:
            _confirm(i, j, texts, threshold, confirmed, uf)
    pairs_compared = len(sim_pairs | lsh_pairs)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    clusters: list[Cluster] = []
    for root in sorted(groups, key=lambda r: min(groups[r])):
        idxs = sorted(groups[root])
        rep = cands[idxs[0]]
        members = [cands[i] for i in idxs[1:]]
        sims = [s for (i, j), s in confirmed.items() if i in idxs and j in idxs]
        cl = Cluster(rep=rep, members=members,
                     similarity=round(min(sims), 4) if sims else 1.0)
        for m in members:
            m.meta = {**(m.meta or {}), "dup_of": rep.candidate_id, "dup_similarity": cl.similarity}
        clusters.append(cl)

    collapsed = n - len(clusters)
    return clusters, {
        "dedup_near_enabled": True,
        "dedup_near_in": n,
        "dedup_near_clusters": len(clusters),
        "dedup_near_collapsed": collapsed,
        "dedup_near_pairs_compared": pairs_compared,
        "dedup_near_threshold": threshold,
        "dedup_near_tokens_saved_estimate": sum(
            m.token_estimate or 0 for cl in clusters for m in cl.members),
    }


def propagate(clusters: list[Cluster]) -> int:
    """Copy the representative's judgement onto its cluster members. Returns members updated.

    Members are flagged `decision_source="propagated"` so a later audit can separate a judged
    verdict from an inherited one — never silently identical in the records.
    """
    updated = 0
    for cl in clusters:
        if cl.rep.relevance is None:
            continue
        for m in cl.members:
            m.relevance, m.injection, m.decision = cl.rep.relevance, cl.rep.injection, cl.rep.decision
            m.meta = {**(m.meta or {}), "decision_source": "propagated",
                      "propagated_from": cl.rep.candidate_id}
            updated += 1
    return updated
