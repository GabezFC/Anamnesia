"""Pure statistics primitives with no app imports (ANA-108)."""
from __future__ import annotations

import math
import random as _random
from typing import Iterable

_Z95 = 1.959963984540054


def wilson_ci(k: int, n: int, z: float = _Z95) -> dict:
    """Wilson score interval for a binomial rate k/n. n == 0 -> no estimate (never a fake 0%)."""
    if n <= 0:
        return {"k": k, "n": n, "rate": None, "low": None, "high": None, "half_width": None}
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    lo, hi = max(0.0, centre - half), min(1.0, centre + half)
    return {"k": k, "n": n, "rate": round(p, 4), "low": round(lo, 4), "high": round(hi, 4),
            "half_width": round((hi - lo) / 2, 4)}


def bootstrap_ci(values: Iterable[float | None], seed: int = 20261011, n_boot: int = 2000,
                 alpha: float = 0.05) -> dict:
    """Percentile bootstrap CI of the mean. Deterministic for a given seed."""
    v = [float(x) for x in values if x is not None]
    if not v:
        return {"n": 0, "mean": None, "low": None, "high": None}
    rng = _random.Random(seed)
    n = len(v)
    means = sorted(sum(v[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"n": n, "mean": round(sum(v) / n, 4), "low": round(lo, 4), "high": round(hi, 4)}


def paired_diff_ci(a: Iterable[float | None], b: Iterable[float | None], seed: int = 20261011,
                   n_boot: int = 2000) -> dict:
    """Paired bootstrap of mean(a - b) over items present in BOTH. `excludes_zero` is the only honest
    basis for saying 'A is better/cheaper than B'."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return {"n": 0, "mean_diff": None, "low": None, "high": None, "excludes_zero": None}
    ci = bootstrap_ci([x - y for x, y in pairs], seed=seed, n_boot=n_boot)
    ez = ci["low"] > 0 or ci["high"] < 0
    return {"n": ci["n"], "mean_diff": ci["mean"], "low": ci["low"], "high": ci["high"], "excludes_zero": ez}
