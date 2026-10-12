"""Pure statistics primitives with no app imports (ANA-108)."""
from __future__ import annotations

import math

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
