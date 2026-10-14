"""ANA-189 / ANA-170: offline calibration and measurement of the deterministic router.

Pure stdlib, no model calls, no network. The "truth" used here is the objective difficulty label of
`benchmark/routing_tasks.json` (computed from corpus structure by scripts/gen_routing_tasks.py, not by a
model). It is a PROXY for "minimum tier that solves the task" (t*): it says how hard the task is by
construction, NOT which model solved it. Therefore:

* the regret computed here is an ORDINAL regret over tier indices (under-routing weighs `under_weight`
  times more than over-routing); it is not money and it must never be quoted as savings;
* a calibrated set of cut-offs is only promoted when the EVAL split shows a paired-bootstrap CI that
  excludes zero in favour of the candidate; otherwise the verdict is HOLD and defaults stay as they are.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Sequence

from app.core.stats import paired_diff_ci
from app.routing.policy import RoutingPolicy
from app.routing.router import difficulty_features, difficulty_score
from app.routing.tasks import DIFFICULTIES, Task, split_tasks

LABEL_RANK = {d: i for i, d in enumerate(DIFFICULTIES)}      # easy 0 / medium 1 / hard 2
AUC_TARGET = 0.75                                            # ANA-170 SUCCESS_METRIC
UNDER_WEIGHT = 2.0                                           # under-routing costs 2x over-routing (proxy)
DEFAULT_ANSWER_MAX_DIFFICULTY = 0.75                         # mirror of answer.ANSWER_MAX_DIFFICULTY (no import cycle)


# ------------------------------------------------------------------ scoring
def score_tasks(tasks: Sequence[Task], policy: RoutingPolicy, context_tokens: int = 0, vocab=None) -> list[float]:
    """Difficulty score per task (same function the router uses). Query (+ optional corpus vocab) only: no
    ground truth, label, risk or answer field is read."""
    return [difficulty_score(difficulty_features(t.query, context_tokens, policy, vocab), policy) for t in tasks]


def level_of(score: float, cutoffs: Sequence[float]) -> int:
    return sum(1 for c in cutoffs if score >= c)


def tier_index(level: int, n_levels: int, n_tiers: int) -> int:
    """Same level->tier index mapping as router.route (floor/risk bump excluded: this is the raw score)."""
    return round(level * (n_tiers - 1) / (n_levels - 1)) if n_levels > 1 else 0


# ------------------------------------------------------------------ metrics
def auc(low: Sequence[float], high: Sequence[float]) -> float | None:
    """P(score_high > score_low) + 0.5 P(tie)  (Mann-Whitney U / (n*m)). None if either side is empty."""
    if not low or not high:
        return None
    srt = sorted(low)
    import bisect
    wins = 0.0
    for h in high:
        lo = bisect.bisect_left(srt, h)
        hi = bisect.bisect_right(srt, h)
        wins += lo + 0.5 * (hi - lo)
    return round(wins / (len(low) * len(high)), 4)


def entropy_bits(counts: Counter | dict) -> float:
    n = sum(counts.values())
    if n <= 0:
        return 0.0
    return round(-sum((c / n) * math.log2(c / n) for c in counts.values() if c), 4) + 0.0   # +0.0: no '-0.0'


def confusion(labels: Sequence[str], preds: Sequence[int], n_classes: int) -> list[list[int]]:
    """rows = label (easy, medium, hard), cols = predicted tier index (0..n_classes-1)."""
    m = [[0] * n_classes for _ in DIFFICULTIES]
    for lab, p in zip(labels, preds):
        m[LABEL_RANK[lab]][p] += 1
    return m


def ordinal_regret(label: str, pred_idx: int, n_tiers: int, under_weight: float = UNDER_WEIGHT) -> float:
    """Needed tier index (proxy) = label rank scaled onto the tiers present; cost of missing it."""
    need = round(LABEL_RANK[label] * (n_tiers - 1) / (len(DIFFICULTIES) - 1))
    d = pred_idx - need
    return float(-d * under_weight) if d < 0 else float(d)


def distribution_report(tasks: Sequence[Task], scores: Sequence[float], cutoffs: Sequence[float],
                        n_tiers: int = 3) -> dict:
    n_levels = len(cutoffs) + 1
    levels = [level_of(s, cutoffs) for s in scores]
    idx = [tier_index(lv, n_levels, n_tiers) for lv in levels]
    by_label: dict[str, list[float]] = {d: [] for d in DIFFICULTIES}
    for t, s in zip(tasks, scores):
        by_label[t.difficulty_label].append(s)
    tier_counts = Counter(i + 1 for i in idx)                     # 1-based, like registry tiers
    return {
        "n": len(scores),
        "label_counts": {d: len(v) for d, v in by_label.items()},
        "score_mean_by_label": {d: (round(sum(v) / len(v), 4) if v else None) for d, v in by_label.items()},
        "auc_easy_lt_hard": auc(by_label["easy"], by_label["hard"]),
        "auc_easy_lt_medium": auc(by_label["easy"], by_label["medium"]),
        "auc_medium_lt_hard": auc(by_label["medium"], by_label["hard"]),
        "level_counts": dict(sorted(Counter(levels).items())),
        "tier_counts": dict(sorted(tier_counts.items())),
        "tier_entropy_bits": entropy_bits(tier_counts),
        "distinct_tiers": len(tier_counts),
        "confusion_label_x_tier_index": confusion([t.difficulty_label for t in tasks], idx, n_tiers),
        "mean_ordinal_regret": round(sum(ordinal_regret(t.difficulty_label, i, n_tiers)
                                         for t, i in zip(tasks, idx)) / max(1, len(idx)), 4),
    }


# ------------------------------------------------------------------ grids and calibration
def cutoff_grid(n_cutoffs: int = 3, step: float = 0.05, lo: float = 0.05, hi: float = 0.95) -> list[tuple]:
    pts = [round(lo + i * step, 4) for i in range(int(round((hi - lo) / step)) + 1)]
    return [c for c in itertools.combinations(pts, n_cutoffs)]


def _regrets(tasks, scores, cutoffs, n_tiers) -> list[float]:
    n_levels = len(cutoffs) + 1
    return [ordinal_regret(t.difficulty_label, tier_index(level_of(s, cutoffs), n_levels, n_tiers), n_tiers)
            for t, s in zip(tasks, scores)]


def grid_search_cutoffs(tasks, scores, grid, n_tiers: int = 3, require_non_constant: bool = False) -> list[dict]:
    """Every grid point scored on the given tasks; sorted by (mean regret, -entropy, cutoffs): deterministic.
    `require_non_constant` drops cut-offs that send every task to one tier (the ANA-170 gate): without it a
    weak router "wins" the proxy by collapsing to the middle tier."""
    rows = []
    for c in grid:
        reg = _regrets(tasks, scores, c, n_tiers)
        n_levels = len(c) + 1
        tiers = Counter(tier_index(level_of(s, c), n_levels, n_tiers) + 1 for s in scores)
        if require_non_constant and len(tiers) < 2:
            continue
        rows.append({"tier_cutoffs": list(c), "mean_regret": round(sum(reg) / len(reg), 4),
                     "entropy_bits": entropy_bits(tiers), "distinct_tiers": len(tiers)})
    rows.sort(key=lambda r: (r["mean_regret"], -r["entropy_bits"], r["tier_cutoffs"]))
    return rows


def answer_threshold_loss(tasks, scores, thr: float) -> float:
    """Proxy loss of ANSWER_MAX_DIFFICULTY=thr: answering a 'hard' task costs 2 (quality risk), returning
    context for a non-hard task costs 1 (lost saving)."""
    loss = 0.0
    for t, s in zip(tasks, scores):
        answered = s < thr
        if t.difficulty_label == "hard" and answered:
            loss += UNDER_WEIGHT
        elif t.difficulty_label != "hard" and not answered:
            loss += 1.0
    return loss / max(1, len(scores))


def calibrate(tasks: Sequence[Task], policy: RoutingPolicy, seed: int = 42, calibration_frac: float = 0.5,
              n_tiers: int = 3, step: float = 0.05) -> dict:
    """Fit tier_cutoffs and ANSWER_MAX_DIFFICULTY on the calibration split; report EVAL separately.

    verdict PROMOTE only if the candidate is NON-constant and the paired CI of the per-task regret difference
    excludes zero in favour of the candidate both vs the default cut-offs and vs the best constant router
    (eval split). Else HOLD. Candidates that collapse to one tier are excluded from the search."""
    cal, ev = split_tasks(list(tasks), seed=seed, calibration_frac=calibration_frac)
    s_cal, s_ev = score_tasks(cal, policy), score_tasks(ev, policy)
    default_c = tuple(policy.tier_cutoffs)
    grid = cutoff_grid(len(default_c), step=step)
    ranked = grid_search_cutoffs(cal, s_cal, grid, n_tiers, require_non_constant=True)
    best = tuple(ranked[0]["tier_cutoffs"])
    # best CONSTANT router on the calibration split (always tier index k): the bar any router must beat
    const_cal = {k: sum(ordinal_regret(t.difficulty_label, k, n_tiers) for t in cal) / len(cal) for k in range(n_tiers)}
    k_const = min(const_cal, key=lambda k: (const_cal[k], k))
    reg_const = [ordinal_regret(t.difficulty_label, k_const, n_tiers) for t in ev]
    reg_def = _regrets(ev, s_ev, default_c, n_tiers)
    reg_best = _regrets(ev, s_ev, best, n_tiers)
    ci = paired_diff_ci(reg_def, reg_best)                        # mean(default - candidate) > 0 => candidate better
    ci_const = paired_diff_ci(reg_const, reg_best)                # mean(const - candidate) > 0 => beats constant
    # answer threshold
    thr_grid = [round(0.05 * i, 2) for i in range(2, 20)]
    thr_best = min(thr_grid, key=lambda x: (answer_threshold_loss(cal, s_cal, x), x))
    ans_def = [answer_threshold_loss([t], [s], DEFAULT_ANSWER_MAX_DIFFICULTY) for t, s in zip(ev, s_ev)]
    ans_best = [answer_threshold_loss([t], [s], thr_best) for t, s in zip(ev, s_ev)]
    ci_ans = paired_diff_ci(ans_def, ans_best)
    cutoffs_win = bool(ci["excludes_zero"] and (ci["mean_diff"] or 0) > 0
                       and ci_const["excludes_zero"] and (ci_const["mean_diff"] or 0) > 0)
    answer_win = bool(ci_ans["excludes_zero"] and (ci_ans["mean_diff"] or 0) > 0)
    return {
        "seed": seed, "n_calibration": len(cal), "n_eval": len(ev), "n_tiers": n_tiers,
        "proxy_note": "ordinal regret vs difficulty LABEL (not t*, not money); under-routing weight "
                      f"{UNDER_WEIGHT}x",
        "tier_cutoffs": {
            "default": list(default_c), "calibrated": list(best),
            "cal_regret_default": next(r["mean_regret"] for r in grid_search_cutoffs(cal, s_cal, [default_c], n_tiers)),
            "cal_regret_calibrated": ranked[0]["mean_regret"],
            "eval_regret_default": round(sum(reg_def) / len(reg_def), 4),
            "eval_regret_calibrated": round(sum(reg_best) / len(reg_best), 4),
            "eval_paired_diff_ci95": ci,
            "best_constant_tier_index": k_const,
            "eval_regret_best_constant": round(sum(reg_const) / len(reg_const), 4),
            "eval_paired_diff_vs_constant_ci95": ci_const,
            "eval_distribution_default": distribution_report(ev, s_ev, default_c, n_tiers),
            "eval_distribution_calibrated": distribution_report(ev, s_ev, best, n_tiers),
            "top5_on_calibration": ranked[:5], "promote": cutoffs_win,
        },
        "answer_max_difficulty": {
            "default": DEFAULT_ANSWER_MAX_DIFFICULTY, "calibrated": thr_best,
            "eval_loss_default": round(sum(ans_def) / len(ans_def), 4),
            "eval_loss_calibrated": round(sum(ans_best) / len(ans_best), 4),
            "eval_paired_diff_ci95": ci_ans, "promote": answer_win,
        },
        "auc_eval_easy_lt_hard": auc([s for t, s in zip(ev, s_ev) if t.difficulty_label == "easy"],
                                     [s for t, s in zip(ev, s_ev) if t.difficulty_label == "hard"]),
        "verdict": "PROMOTE" if (cutoffs_win or answer_win) else "HOLD",
        "verdict_reason": ("eval CI excludes zero in favour of candidate" if (cutoffs_win or answer_win) else
                           "no demonstrable gain on the eval split (paired CI95 includes zero or favours defaults); "
                           "defaults unchanged"),
    }


# ------------------------------------------------------------------ ANA-190: principled revision helpers
FIT_FEATURES = ("length", "entities", "multi_hop", "context", "code", "reasoning", "classifier", "ungrounded")
FIT_GRID = (0.0, 1.0, 2.0, 4.0)          # coarse on purpose: 88 train tasks cannot support finer weights
FIT_TOLERANCE = 0.01                      # prefer the simplest weight vector within this AUC of the best


def auc_pair(tasks: Sequence[Task], scores: Sequence[float], low: str = "easy", high: str = "hard") -> float | None:
    return auc([s for t, s in zip(tasks, scores) if t.difficulty_label == low],
               [s for t, s in zip(tasks, scores) if t.difficulty_label == high])


def bootstrap_auc_ci(tasks: Sequence[Task], scores: Sequence[float], low: str = "easy", high: str = "hard",
                     n_boot: int = 2000, seed: int = 20261013) -> dict:
    """Percentile bootstrap CI95 of AUC(low<high): easy and hard resampled independently (stratified)."""
    import random
    lo = [s for t, s in zip(tasks, scores) if t.difficulty_label == low]
    hi = [s for t, s in zip(tasks, scores) if t.difficulty_label == high]
    if not lo or not hi:
        return {"auc": None, "low": None, "high": None, "n_low": len(lo), "n_high": len(hi), "n_boot": 0}
    rng = random.Random(seed)
    vals = sorted(auc([rng.choice(lo) for _ in lo], [rng.choice(hi) for _ in hi]) for _ in range(n_boot))
    return {"auc": auc(lo, hi), "low": vals[int(0.025 * (n_boot - 1))], "high": vals[int(0.975 * (n_boot - 1))],
            "n_low": len(lo), "n_high": len(hi), "n_boot": n_boot, "seed": seed}


def score_from_features(feats_rows: Sequence[dict], weights: dict) -> list[float]:
    """Same arithmetic as router.difficulty_score, on precomputed feature rows (fast grid search)."""
    out = []
    for f in feats_rows:
        tot = sum(weights.get(k, 0.0) for k in f)
        out.append(0.0 if tot <= 0 else round(min(1.0, max(0.0, sum(weights.get(k, 0.0) * v for k, v in f.items()) / tot)), 6))
    return out


def fit_weights(tasks: Sequence[Task], policy: RoutingPolicy, vocab=None, grid: Sequence[float] = FIT_GRID,
                features: Sequence[str] = FIT_FEATURES) -> dict:
    """Exhaustive grid over the weights of `features` (others keep policy values), maximising AUC(easy<hard) on
    the GIVEN tasks (pass the TRAIN split only). Among vectors within FIT_TOLERANCE of the best, pick the one with
    fewest non-zero weights, then the smallest weight sum, then lexicographic: deterministic and parsimonious."""
    rows = [difficulty_features(t.query, 0, policy, vocab) for t in tasks]
    present = [f for f in features if rows and f in rows[0]]
    base = dict(policy.weights)
    results = []
    for combo in itertools.product(grid, repeat=len(present)):
        w = dict(base)
        w.update(zip(present, combo))
        a = auc_pair(tasks, score_from_features(rows, w)) or 0.0
        results.append((a, combo))
    best = max(a for a, _ in results)
    cands = [(sum(1 for x in c if x > 0), sum(c), c, a) for a, c in results if a >= best - FIT_TOLERANCE]
    cands.sort()
    chosen = cands[0]
    w = dict(base)
    w.update(zip(present, chosen[2]))
    return {"weights": w, "fitted_features": present, "train_auc": chosen[3], "best_train_auc": best,
            "n_candidates_within_tolerance": len(cands), "grid": list(grid)}


def quantile_cutoffs(scores: Sequence[float], quantiles: Sequence[float]) -> tuple:
    """Tie-aware cut-offs at the given quantiles of the TRAIN score distribution. Scores are discrete (few
    distinct values), so the cut is placed at the MIDPOINT between the quantile value and the next distinct
    value above it: tied scores never straddle a cut and no level is degenerate."""
    s = sorted(scores)
    distinct = sorted(set(s))
    out = []
    for q in quantiles:
        v = s[min(len(s) - 1, int(q * len(s)))]
        nxt = next((d for d in distinct if d > v), None)
        out.append(round((v + nxt) / 2 if nxt is not None else v, 4))
    return tuple(out)
