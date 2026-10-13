"""ANA-185: two different verifiers that must not be confused.

* ESCALATION verifier (`verify_for_escalation`): decides at run time whether a cheap model's answer may be
  accepted or must escalate. It has NO ground truth (production has none): only schema / grounding in the
  retrieved snippets / citation of retrieved notes. Reuses app/routing/verifiers.py.
* SCORING verifier (`verify_with_ground_truth`): used only by benchmarks, with the expected facts/JSON/abstention.

`escalation_error_rates` measures how wrong the LIGHT escalation verifier is against the scoring verifier on
given records: false-accept (LIGHT accepted an answer GT says is wrong => silent quality loss) and
false-reject (LIGHT rejected a correct answer => needless escalation cost). It computes nothing by itself:
the records must come from real runs; tests use synthetic records labelled `data_origin="synthetic"`.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from app.core.stats import wilson_ci
from app.routing.verifiers import (
    VerifyResult,
    extract_cited_ids,
    match_cited_to_retrieved,
    verify_abstention,
    verify_citation,
    verify_fact_match,
    verify_grounding,
    verify_json_schema,
)

DATA_ORIGINS = ("real", "synthetic", "simulated")


@dataclass(frozen=True)
class EscalationVerdict:
    accept: bool
    codes: tuple = ()
    checks: dict = field(default_factory=dict)       # name -> passed (True/False)


def verify_for_escalation(answer: str, snippets: Sequence[str] = (), retrieved_ids: Sequence[str] = (),
                          schema: dict | None = None, require_citation: bool = False,
                          grounding_threshold: float = 0.6) -> EscalationVerdict:
    """No-ground-truth gate. Signature deliberately has no `expected_*` parameter."""
    results: dict[str, VerifyResult] = {}
    if schema is not None:
        results["schema"] = verify_json_schema(answer, schema)
    else:
        results["grounding"] = verify_grounding(answer, list(snippets), grounding_threshold)
    if require_citation:
        cited = match_cited_to_retrieved(extract_cited_ids(answer), retrieved_ids)
        results["citation"] = verify_citation(cited, retrieved_ids)
    codes = tuple(r.failure_code for r in results.values() if r.passed is False and r.failure_code)
    return EscalationVerdict(not codes, codes, {k: r.passed for k, r in results.items()})


def verify_with_ground_truth(answer: str, ground_truth: dict) -> VerifyResult:
    """Scoring verifier (benchmark only): needs expected facts, expected_json or answerable=False."""
    if ground_truth.get("answerable") is False:
        return verify_abstention(answer)
    if "expected_json" in ground_truth:
        r = verify_json_schema(answer, {"type": "object", "required": list(ground_truth["expected_json"])})
        if r.passed is not True:
            return r
        import json
        try:
            got = json.loads(answer) if isinstance(answer, str) else answer
        except (ValueError, TypeError):
            return r
        ok = all(str(got.get(k)) == str(v) for k, v in ground_truth["expected_json"].items())
        return r if ok else VerifyResult(False, r.level, "json_value_mismatch", {})
    return verify_fact_match(answer, ground_truth.get("expected_facts") or [])


def escalation_error_rates(records: Iterable[dict], data_origin: str) -> dict:
    """records: {"light_accept": bool, "gt_correct": bool}. `data_origin` is mandatory so that a rate computed on
    synthetic data can never be mistaken for a measurement."""
    if data_origin not in DATA_ORIGINS:
        raise ValueError(f"data_origin must be one of {DATA_ORIGINS}")
    recs = list(records)
    accepted = [r for r in recs if r["light_accept"]]
    rejected = [r for r in recs if not r["light_accept"]]
    wrong_acc = sum(1 for r in accepted if not r["gt_correct"])
    right_rej = sum(1 for r in rejected if r["gt_correct"])
    return {
        "data_origin": data_origin, "n": len(recs),
        "false_accept": wilson_ci(wrong_acc, len(accepted)),     # P(GT wrong | LIGHT accepted)
        "false_reject": wilson_ci(right_rej, len(rejected)),     # P(GT right | LIGHT rejected)
        "claimable": data_origin == "real" and len(recs) >= 30,
        "note": ("not a measurement" if data_origin != "real" else
                 "measurement" if len(recs) >= 30 else "real but n<30: indicative only"),
    }
