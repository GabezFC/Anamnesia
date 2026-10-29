"""EXPERIMENTAL / NOT WIRED (no runtime consumer; only tests import it). ANA-193: deterministic A/B bucketing between two routing policies. OFF by default.

* Only active when ANAMNESIA_ROUTING_AB=1 (flag) AND risk == "low": medium/high risk always get arm A.
* Bucket = sha256(salt + query_fingerprint) -> [0,1): the same query always lands in the same arm, no RNG.
* This module only DECIDES the arm and analyses outcomes; it never calls a model. Wiring `assign()` into the
  answer path is deliberately NOT done (ANA-193 stays PARCIAL/HOLD until real runs exist).
* Guardrail: if arm B's grounding rate is worse than arm A's by more than `max_drop` (Wilson-based, using the
  upper bound of A's lower... see `guardrail`), the experiment must stop: verdict "STOP".
* Effect size: paired/independent bootstrap CI95 via app/benchmark/statistics.py. No CI excluding zero => HOLD.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Sequence

from app.core.stats import bootstrap_ci
from app.core.stats import wilson_ci
from app.services.query_fp import fingerprint

ENV_FLAG = "ANAMNESIA_ROUTING_AB"
ARMS = ("A", "B")


def ab_enabled() -> bool:
    return os.getenv(ENV_FLAG, "").strip() == "1"


def bucket(query: str, salt: str = "anamnesia-ab-1") -> float:
    """Deterministic value in [0,1) from the query fingerprint (order/case/accent-insensitive per fingerprint())."""
    fp = "|".join(fingerprint(query)) or query.strip().lower()
    h = hashlib.sha256(f"{salt}:{fp}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def assign(query: str, risk: str, share_b: float = 0.5, salt: str = "anamnesia-ab-1",
           force_enabled: bool | None = None) -> dict:
    """-> {"arm": "A"|"B", "eligible": bool, "reason": str, "bucket": float|None}."""
    on = ab_enabled() if force_enabled is None else force_enabled
    if not on:
        return {"arm": "A", "eligible": False, "reason": "ab_disabled", "bucket": None}
    if risk != "low":
        return {"arm": "A", "eligible": False, "reason": "risk_not_low", "bucket": None}
    if not 0.0 <= share_b <= 1.0:
        raise ValueError("share_b must be in [0,1]")
    b = bucket(query, salt)
    return {"arm": "B" if b < share_b else "A", "eligible": True, "reason": "bucket", "bucket": round(b, 6)}


def guardrail(records: Sequence[dict], max_drop: float = 0.05, min_n: int = 30) -> dict:
    """Grounding-rate guardrail on records {"arm", "grounded": bool}. STOP when B's rate is below A's by more than
    `max_drop` AND the Wilson CIs are separated (B.high < A.low). Fewer than `min_n` per arm: WAIT."""
    a = [r for r in records if r["arm"] == "A" and r.get("grounded") is not None]
    b = [r for r in records if r["arm"] == "B" and r.get("grounded") is not None]
    ca = wilson_ci(sum(bool(r["grounded"]) for r in a), len(a))
    cb = wilson_ci(sum(bool(r["grounded"]) for r in b), len(b))
    if len(a) < min_n or len(b) < min_n:
        verdict, why = "WAIT", f"need >= {min_n} per arm (A={len(a)}, B={len(b)})"
    else:
        drop = ca["rate"] - cb["rate"]
        if drop > max_drop and cb["high"] < ca["low"]:
            verdict, why = "STOP", f"B grounding {cb['rate']} < A {ca['rate']} beyond {max_drop} with separated CIs"
        else:
            verdict, why = "OK", "no significant grounding drop"
    return {"verdict": verdict, "reason": why, "arm_a": ca, "arm_b": cb}


def effect(records: Iterable[dict], metric: str = "cost") -> dict:
    """Mean of `metric` per arm and bootstrap CI95 of mean(B) - mean(A) (independent arms).
    `excludes_zero` is the only basis to claim a difference."""
    recs = list(records)
    va = [float(r[metric]) for r in recs if r["arm"] == "A" and r.get(metric) is not None]
    vb = [float(r[metric]) for r in recs if r["arm"] == "B" and r.get(metric) is not None]
    ca, cb = bootstrap_ci(va), bootstrap_ci(vb)
    if not va or not vb:
        return {"metric": metric, "A": ca, "B": cb, "diff_B_minus_A": None, "excludes_zero": None}
    # CI of the difference of means by resampling both arms with the same seeded generator
    import random
    rng = random.Random(20261011)
    diffs = sorted(sum(vb[rng.randrange(len(vb))] for _ in vb) / len(vb)
                   - sum(va[rng.randrange(len(va))] for _ in va) / len(va) for _ in range(2000))
    lo, hi = diffs[int(0.025 * 2000)], diffs[min(1999, int(0.975 * 2000))]
    return {"metric": metric, "A": ca, "B": cb,
            "diff_B_minus_A": {"mean": round(cb["mean"] - ca["mean"], 6), "low": round(lo, 6), "high": round(hi, 6)},
            "excludes_zero": bool(lo > 0 or hi < 0)}


def analyze(records: Sequence[dict], metric: str = "cost", data_origin: str = "real") -> dict:
    """Combine guardrail + effect into a verdict. Anything but real data with an unbroken guardrail and a CI that
    excludes zero is HOLD. Never states savings: `claimable_saving` is only True under all those conditions."""
    g = guardrail(records)
    e = effect(records, metric)
    claim = (data_origin == "real" and g["verdict"] == "OK" and bool(e["excludes_zero"])
             and e["diff_B_minus_A"] is not None and e["diff_B_minus_A"]["high"] < 0)
    verdict = "STOP" if g["verdict"] == "STOP" else ("ADOPT_CANDIDATE" if claim else "HOLD")
    return {"data_origin": data_origin, "guardrail": g, "effect": e, "verdict": verdict, "claimable_saving": claim}
