"""Adaptive candidate selection: how many candidates deserve a paid judgement (§8, §9, §14, §21).

Three independent mechanisms, each individually switchable so each can be measured on its own:

ADAPTIVE K (§8)
---------------
A fixed top_k=8 pays the same price for every query. `plan_k` picks a per-query K instead.

WHAT THE CALIBRATION ACTUALLY SHOWED (2026-09-27, 120 questions / 520 notes,
scripts/calibrate_heuristics.py — the numbers below are measured, not assumed)

  recall of the deterministic ranker at K, by query complexity class:

      complexity    n      K=2     K=3     K=4     K=6     K=8    K=12    K=16    K=20
      SIMPLE       77    0.987   1.000   1.000   1.000   1.000   1.000   1.000   1.000
      MEDIUM        9    1.000   1.000   1.000   1.000   1.000   1.000   1.000   1.000
      COMPLEX      18    0.444   0.444   0.444   0.500   0.500   0.833   0.944   1.000

Two findings, both surprising, both load-bearing:

  1. For SIMPLE/MEDIUM queries (86 of 104 answerable = 83%) the answer is inside the top 3. K=8 was
     paying for five candidates that the ranker had already ruled out. Worst observed position: 2.
  2. For COMPLEX/multi-hop queries the fixed K=8 was NOT conservative, it was LOSING RECALL: only
     50% of those answers were inside the top 8, and full coverage needed K=20 (worst position 18).

So adaptive K is not primarily a saving mechanism — it is a REALLOCATION: it stops overspending on
the easy 83% and starts spending enough on the hard 17%, where the frozen baseline was silently
dropping half the answers. The honest report of this mechanism must state both directions.

WHY RANK CONFIDENCE IS MEASURED BUT NOT USED TO SHRINK K
--------------------------------------------------------
The first design shrank K when the deterministic score curve looked "decisive". Measured on the same
120 questions, that rule FIRED ZERO TIMES: the retrieval scores arrive in wide ties (see
prefilter.normalize_scores), so the combined margin between rank 0 and rank 1 was 0.060 on average
for questions answered at rank 0 and 0.044 for questions whose answer sat at rank >= 8 — the signal
does not separate the two populations at all. Every alternative cheap rule tried had either zero
coverage or ~2% coverage:

      rule                                    fires   precision   coverage
      comb_margin >= 0.15 (original)              0         n/a     0.0000
      lex_top >= 0.80 and lex_margin >= 0.25      0         n/a     0.0000
      lex_margin >= 0.30                          2      1.0000     0.0192

`rank_confidence` is therefore still computed and recorded (it is free, and a future corpus may make
it informative) but it may only ever RAISE K, never lower it below the class floor. A signal that has
not been shown to predict anything is not allowed to remove candidates.

EARLY STOPPING (§9)
-------------------
After each wave, `should_stop` asks whether another wave can plausibly change the answer. It stops
only on positive evidence of saturation: enough strong survivors AND a decisive gap between the last
accepted candidate and the best remaining one. It never stops merely because tokens were spent. This
is what makes the raised COMPLEX ceiling affordable: the ceiling is an upper bound on what MAY be
bought, and early stopping is what decides whether it actually is.

ZERO-EVIDENCE DROP (§21, §14)
-----------------------------
Some candidates have literally no connection to the query: no query term anywhere in path, heading
or body, and a bottom-ranked retrieval score. `zero_evidence` flags them. They are NOT dropped by
default, and the measurement says they must not be: on the synthetic corpus the rule flagged 48.8%
of all candidates but 9 of the flagged were GROUND-TRUTH notes (reachable only through the graph,
sharing no vocabulary with the question). That is a hard veto on promotion — the flag stays a shadow
metric.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from app.schemas.models import Candidate
from app.services.prefilter import lexical_overlap, terms
from app.services.query_fp import QueryProfile

ADAPTIVE_VERSION = "adaptive-v2"

# Starting K and escalation steps per complexity class (§8, §18), CALIBRATED on the measured
# recall@K table in the module docstring rather than chosen for looking reasonable.
#
#   SIMPLE / MEDIUM : the answer was inside the top 3 in 100% of 86 measured cases (worst: 2).
#                     Start at 4 — one slot of margin above the worst observed position — and keep a
#                     +2 escalation for queries unlike the calibration set.
#   COMPLEX         : recall was 0.500 at K=8 and only reached 1.000 at K=20 (worst: 18). The floor
#                     must therefore be well above the old fixed 8, with escalation to 20.
#   AMBIGUOUS       : too few samples (2) to calibrate. Treated as COMPLEX on purpose: an unclassifiable
#                     query is the one case where under-spending is unrecoverable.
DEFAULT_K_PLAN: dict[str, tuple[int, tuple[int, ...]]] = {
    "SIMPLE":    (4, (2,)),
    "MEDIUM":    (4, (2,)),
    "COMPLEX":   (12, (8,)),
    "AMBIGUOUS": (12, (8,)),
}
# Absolute floor: no plan may ever send fewer than this, regardless of class or signal.
K_FLOOR = 3


@dataclass
class KPlan:
    start: int
    steps: tuple[int, ...]
    reason: str
    max_total: int

    def waves(self) -> list[int]:
        """Cumulative K after each wave, capped at max_total."""
        out, k = [min(self.start, self.max_total)], min(self.start, self.max_total)
        for s in self.steps:
            k = min(k + s, self.max_total)
            if k != out[-1]:
                out.append(k)
        return out


@dataclass
class RankConfidence:
    """Shape of the deterministic score curve. High confidence = the ranker is already decisive."""
    top: float
    margin: float          # gap between best and second
    tail_ratio: float      # mean of positions 3..n over the top score
    confident: bool
    n: int

    def to_dict(self) -> dict:
        return {"rank_top": round(self.top, 4), "rank_margin": round(self.margin, 4),
                "rank_tail_ratio": round(self.tail_ratio, 4), "rank_confident": self.confident}


def rank_confidence(query: str, ordered: list[Candidate], lexical_weight: float = 0.3) -> RankConfidence:
    """Measure how decisive the deterministic ranking is, using the SAME combined score the
    pre-filter ordered by (retrieval percentile + lexical overlap), not the raw retrieval score —
    otherwise a wide tie in the retrieval score would read as "no margin" when the lexical signal
    had in fact separated the candidates cleanly."""
    if not ordered:
        return RankConfidence(0.0, 0.0, 0.0, False, 0)
    qt = terms(query)
    from app.services.prefilter import normalize_scores
    norm = normalize_scores(ordered)
    w = max(0.0, min(1.0, lexical_weight))
    combined = [(1 - w) * norm.get(c.candidate_id, 0.0) + w * lexical_overlap(qt, c) for c in ordered]
    top = combined[0]
    second = combined[1] if len(combined) > 1 else 0.0
    tail = combined[2:] or [0.0]
    margin = top - second
    tail_ratio = (statistics.fmean(tail) / top) if top > 0 else 0.0
    # Confident = a clear leader AND a tail that is not competitive with it.
    confident = bool(top >= 0.55 and margin >= 0.15 and tail_ratio <= 0.65)
    return RankConfidence(top, margin, tail_ratio, confident, len(ordered))


def plan_k(profile: QueryProfile, conf: RankConfidence, *, max_total: int,
           plan: dict[str, tuple[int, tuple[int, ...]]] | None = None) -> KPlan:
    """Pick the starting K and escalation steps for one query.

    Confidence may only RAISE K. See the module docstring: no cheap confidence signal was shown to
    predict "the answer is at rank 0" on the calibration set, so allowing it to lower K would be
    trading measured recall for an unmeasured hunch.
    """
    table = plan or DEFAULT_K_PLAN
    start, steps = table.get(profile.complexity, table["MEDIUM"])
    reason = f"complexity={profile.complexity}"
    # NOTE: an earlier version added +2 whenever `conf.confident` was False. Since no confidence rule
    # fires on this corpus (see the module docstring), that condition was true for 120/120 queries —
    # a "signal" that fires always is a constant, and it was simply inflating every SIMPLE plan from
    # 4 to 6 while pretending to be adaptive. The class floor already encodes the calibrated margin,
    # so the bump was removed. `conf` is still recorded for future corpora.
    if profile.multi_hop_hint:
        # Multi-hop answers landed as deep as rank 18 in the calibration set.
        start += 4
        reason += ",multi_hop"
    start = max(K_FLOOR, min(start, max_total))
    return KPlan(start=start, steps=steps, reason=reason, max_total=max_total)


@dataclass
class StopDecision:
    stop: bool
    reason: str
    strong: int
    gap: float | None


def should_stop(judged: list[Candidate], remaining: list[Candidate], *,
                keep_threshold: float, review_threshold: float,
                min_strong: int = 1, max_accept_rank: int = 3,
                max_results: int = 10, order: list[Candidate] | None = None) -> StopDecision:
    """Decide whether the next wave of candidates can still change the outcome (§9).

    THE STOP SIGNAL IS THE RANK OF THE ACCEPTED CANDIDATE, NOT A SCORE GAP.
    Two score-gap formulations were tried and both were measured to be non-signals:

      absolute gap  min(accepted.score) - max(remaining.score)  = 0.045 on 12/12 queries
      relative gap  the same, divided by min(accepted.score)     = 0.0520 on 108/108 judgements
                                                                   (mean = min = max = p90)

    The hybrid retriever assigns scores by RANK inside fixed bands (BM25 hits 1.00 -> 0.55, graph
    neighbours 0.50 -> 0.30), so the difference between adjacent ranks is a constant of the scoring
    scheme and says nothing about the query. A threshold of 0.25 against a constant 0.052 meant early
    stopping could never fire: it silently cost one extra request per query (340 tokens) and returned
    nothing while reporting itself as enabled.

    What DOES carry signal, measured over 93 judged queries on the synthetic corpus:

        rank of the first KEEP:   rank 0 -> 82,  rank 1 -> 2,  rank 2 -> 9,  deeper -> 0
        ground truth ranked deeper than the first KEEP:   0 / 93

    So when the judge confirms a KEEP at rank < `max_accept_rank`, everything the ranker placed below
    it was measured never to contain the answer. That is the evidence, and it is what we stop on.
    `max_accept_rank` defaults to 3 = one position of margin beyond the worst observed rank (2).

    Every other guard still applies: enough strong survivors, and the weakest accepted candidate must
    sit clearly above the REVIEW band, so an accepted-but-borderline verdict never ends the search.
    """
    strong = [c for c in judged if (c.relevance or 0) >= keep_threshold]
    n_strong = len(strong)
    if not remaining:
        return StopDecision(True, "no_candidates_left", n_strong, None)
    if n_strong < min_strong:
        return StopDecision(False, "not_enough_strong", n_strong, None)
    if n_strong >= max_results:
        return StopDecision(True, "answer_full", n_strong, None)

    weakest_accepted = min((c.relevance or 0) for c in strong)
    if weakest_accepted - review_threshold < 0.05:
        return StopDecision(False, "accepted_too_close_to_review", n_strong, None)

    # Rank of the best accepted candidate in the deterministic order. `order` is the full ranked pool
    # when the caller has it; otherwise the judged prefix is a faithful stand-in, since waves consume
    # the pool in rank order.
    ranked = order if order is not None else judged
    positions = {id(c): i for i, c in enumerate(ranked)}
    accept_rank = min((positions.get(id(c), len(ranked)) for c in strong), default=len(ranked))
    if accept_rank < max_accept_rank:
        return StopDecision(True, "accepted_within_calibrated_rank", n_strong, float(accept_rank))
    return StopDecision(False, "accepted_too_deep", n_strong, float(accept_rank))


@dataclass
class ZeroEvidence:
    """Candidates with no measurable connection to the query (§21). Shadow-mode by default."""
    flagged: list[Candidate] = field(default_factory=list)
    agreements: int = 0        # judge also said DROP
    disagreements: int = 0     # judge said KEEP/REVIEW -> the heuristic would have lost recall
    scores: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        total = self.agreements + self.disagreements
        return {"zero_evidence_flagged": len(self.flagged),
                "zero_evidence_agreements": self.agreements,
                "zero_evidence_disagreements": self.disagreements,
                "zero_evidence_precision": round(self.agreements / total, 4) if total else None,
                "zero_evidence_max_relevance": round(max(self.scores), 4) if self.scores else None}


def zero_evidence(query: str, cands: list[Candidate]) -> list[Candidate]:
    """Flag candidates with ZERO query-term overlap in path, heading and body.

    Deliberately the strictest possible rule: any single shared significant term disqualifies a
    candidate from being flagged. A note can still be relevant with zero lexical overlap (that is
    precisely what the graph stage is for), which is why this only ever feeds shadow metrics until
    its agreement with the judge has been measured.
    """
    qt = terms(query)
    if not qt:
        return []
    out = []
    for c in cands:
        if lexical_overlap(qt, c) == 0.0:
            out.append(c)
    return out
