"""Deterministic pre-filter: cheap ranking BEFORE any paid judge sees a candidate (zero tokens).

Rationale (measured 2026-09-27 over 42 graphify_jev runs in benchmark.db):
JEV was judging ~50 candidates per query at ~19,400 input tokens, to keep a median of 1.
94.9% of all candidates scored below the DROP threshold. Sending every candidate to a paid
judge is the single largest token cost in the pipeline, and most of it is spent proving that
obviously-irrelevant notes are irrelevant.

This module ranks candidates with a hybrid deterministic signal and hands the judge only the
top-K. Measured survivor retention on the recorded runs (rank of JEV survivors under each scorer):

    scorer                     top5   top10  top20  top25
    graphify score only        50.0%  77.1%  83.3%  91.7%
    lexical path+heading       66.7%  66.7%  77.1%  81.2%
    hybrid 50/50               66.7%  66.7%  83.3%  87.5%

No single cheap signal dominates, so the default K is deliberately conservative (25 = half the
judge's current input for ~92% survivor retention). The scorer is graph/lexical only: no model
call, no embedding, no network. Tune with PREFILTER_TOP_K / PREFILTER_LEXICAL_WEIGHT.

MEASUREMENT CAVEAT: the validation replayed the recorded `candidates` rows, which store no
snippet text, so the lexical signal was scored on path + heading only. Under that handicap
weight 0.0 and 0.3 both retain 91.7% at K=25; 0.3 is the default because it additionally
rescues notes whose filename matches the query (see tests/test_prefilter.py). Re-validate the
weight with a live benchmark run now that full snippets are available.
"""
from __future__ import annotations

import re
import unicodedata

from app.schemas.models import Candidate

# Portuguese + English function words: they appear in every note and carry no retrieval signal.
STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra com sem
e ou que qual quais quando como onde porque se ser foi era sao esta estao mais menos ja ainda sobre
entre ate tambem foram tem ter fazer feito sido the of and to in is are was what how why which who for
on with be it this that my me you he she his her they them there then than at from by as or not no
""".split())

_TOKEN = re.compile(r"[a-z0-9]{2,}")


def _fold(text: str) -> str:
    """Lowercase and strip diacritics so 'decisão' matches 'decisao' (vault is Portuguese)."""
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def terms(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(_fold(text)) if t not in STOPWORDS and len(t) > 2}


def lexical_overlap(query_terms: set[str], c: Candidate) -> float:
    """Fraction of query terms present in the candidate's path + heading + snippet.

    Path and heading are weighted implicitly: in this vault the filename encodes the topic
    (`decisao-driver-asyncpg.md`), so a path hit is a strong, free relevance signal.
    """
    if not query_terms:
        return 0.0
    haystack = terms(c.source_file.replace("/", " ").replace("-", " ").replace("_", " "))
    haystack |= terms(c.section or "")
    hits_meta = len(query_terms & haystack)
    hits_body = len(query_terms & terms(c.snippet or ""))
    # A term in the path/heading counts full; in the body it counts half.
    return min(1.0, (hits_meta + 0.5 * hits_body) / len(query_terms))


def normalize_scores(cands: list[Candidate]) -> dict[str, float]:
    """Map retrieval scores to [0,1] by TIE-AVERAGED RANK PERCENTILE, not min-max.

    Min-max is wrong here: Graphify frequently returns a large cluster of candidates with an
    identical top score, and min-max would award every one of them 1.0 — enough to outvote a
    candidate with strong lexical evidence (measured failure: a note whose filename matched the
    query was cut while 29 tied, unrelated notes survived). Rank percentile with tie averaging
    makes a wide tie worth its average position (~0.5), so ties cannot dominate the ranking.

    Scores are not calibrated across queries, so only within-query ordering is meaningful.
    """
    if not cands:
        return {}
    scored = [(c.candidate_id, c.score if c.score is not None else float("-inf")) for c in cands]
    n = len(scored)
    if n == 1:
        return {scored[0][0]: 1.0}
    # Group by identical score; every member of a group gets the group's average percentile.
    order = sorted(range(n), key=lambda i: -scored[i][1])
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scored[order[j + 1]][1] == scored[order[i]][1]:
            j += 1
        # positions i..j share a score -> average rank, converted to a percentile (1.0 = best)
        avg_rank = (i + j) / 2.0
        pct = 1.0 - avg_rank / (n - 1)
        for k in range(i, j + 1):
            out[scored[order[k]][0]] = pct
        i = j + 1
    return out


def rank(query: str, cands: list[Candidate], lexical_weight: float = 0.5) -> list[Candidate]:
    """Order candidates best-first by hybrid (retrieval score, lexical overlap). Pure function."""
    qt = terms(query)
    norm = normalize_scores(cands)
    w = max(0.0, min(1.0, lexical_weight))

    def key(c: Candidate) -> tuple:
        combined = (1 - w) * norm.get(c.candidate_id, 0.0) + w * lexical_overlap(qt, c)
        # Deterministic tie-break so identical scores never reorder between runs.
        return (-combined, -(c.score or 0.0), c.source_file, c.section or "")

    return sorted(cands, key=key)


def prefilter(query: str, cands: list[Candidate], top_k: int,
              lexical_weight: float = 0.5) -> tuple[list[Candidate], list[Candidate], dict]:
    """Split candidates into (sent_to_judge, withheld, metrics).

    top_k <= 0 disables the pre-filter entirely (everything is judged) so the previous
    behaviour remains reproducible for benchmarking.
    """
    if top_k <= 0 or len(cands) <= top_k:
        return cands, [], {
            "prefilter_enabled": top_k > 0,
            "prefilter_top_k": top_k,
            "prefilter_in": len(cands),
            "prefilter_sent": len(cands),
            "prefilter_withheld": 0,
        }
    ordered = rank(query, cands, lexical_weight)
    sent, withheld = ordered[:top_k], ordered[top_k:]
    return sent, withheld, {
        "prefilter_enabled": True,
        "prefilter_top_k": top_k,
        "prefilter_lexical_weight": lexical_weight,
        "prefilter_in": len(cands),
        "prefilter_sent": len(sent),
        "prefilter_withheld": len(withheld),
        "prefilter_tokens_saved_estimate": sum(c.token_estimate or 0 for c in withheld),
    }
