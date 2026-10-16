"""Análise de divergência Laya × JEV e métricas de classificação (puras, sem I/O). ANAM-043.

Entrada: pares (decisão_laya, decisão_jev) por item (+ rótulo opcional 0/1 de relevância).
Todo número sai com rótulo MEASURED (calculado sobre dados reais da amostra) — a AMOSTRA pode ser enviesada
(p.ex. o histórico só tem pares quando os dois rodaram); isso é dito em `caveat`.
"""
from __future__ import annotations

from typing import Iterable

from app.decision.types import DROP, KEEP, MEASURED, QUARANTINE, REVIEW, UNKNOWN, labeled

CLASSES = (KEEP, REVIEW, DROP, QUARANTINE)


def survives(decision: str, review_action: str = "keep") -> bool:
    return decision == KEEP or (decision == REVIEW and review_action == "keep")


def prf(y: list[int], pred: list[int]) -> dict:
    tp = sum(1 for a, b in zip(y, pred) if a and b)
    fp = sum(1 for a, b in zip(y, pred) if not a and b)
    fn = sum(1 for a, b in zip(y, pred) if a and not b)
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    rd = lambda v: None if v is None else round(v, 4)  # noqa: E731
    return {"tp": tp, "fp": fp, "fn": fn, "precision": rd(p), "recall": rd(r), "f1": rd(f1)}


def percentile(vals: list[float], q: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def auc(scores: list[float], y: list[int]) -> float | None:
    pos = [s for s, t in zip(scores, y) if t]
    neg = [s for s, t in zip(scores, y) if not t]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def divergence(pairs: Iterable[tuple[str, str]], labels: list[int] | None = None, review_action: str = "keep") -> dict:
    """pairs = [(laya_decision, jev_decision)]. Concordância exata e de sobrevivência, kappa e matriz."""
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return {"n": labeled(0, MEASURED), "agreement_rate": labeled(None, UNKNOWN, "sem pares Laya×JEV"),
                "caveat": "sem amostra"}
    exact = sum(1 for a, b in pairs if a == b)
    sa = [survives(a, review_action) for a, _ in pairs]
    sb = [survives(b, review_action) for _, b in pairs]
    surv = sum(1 for x, y in zip(sa, sb) if x == y)
    matrix: dict[str, dict[str, int]] = {a: {b: 0 for b in CLASSES} for a in CLASSES}
    for a, b in pairs:
        if a in matrix and b in matrix[a]:
            matrix[a][b] += 1
    # kappa de Cohen sobre as 4 classes
    pa = exact / n
    pe = sum((sum(1 for a, _ in pairs if a == c) / n) * (sum(1 for _, b in pairs if b == c) / n) for c in CLASSES)
    kappa = (pa - pe) / (1 - pe) if pe < 1 else None
    out = {
        "n": labeled(n, MEASURED),
        "agreement_rate": labeled(round(exact / n, 4), MEASURED),
        "survival_agreement_rate": labeled(round(surv / n, 4), MEASURED),
        "cohen_kappa": labeled(None if kappa is None else round(kappa, 4), MEASURED),
        "laya_keep_jev_drop": sum(1 for a, b in pairs if survives(a) and not survives(b)),
        "laya_drop_jev_keep": sum(1 for a, b in pairs if not survives(a) and survives(b)),
        "matrix_rows_laya_cols_jev": matrix,
        "caveat": "amostra dos itens em que os dois providers responderam; pode ser enviesada pela estratégia",
    }
    if labels is not None and len(labels) == n:
        out["vs_labels"] = {
            "laya": prf(labels, [int(x) for x in sa]), "jev": prf(labels, [int(x) for x in sb]),
            "laya_right_jev_wrong": sum(1 for x, y, t in zip(sa, sb, labels) if x == bool(t) and y != bool(t)),
            "jev_right_laya_wrong": sum(1 for x, y, t in zip(sa, sb, labels) if y == bool(t) and x != bool(t)),
        }
    return out
