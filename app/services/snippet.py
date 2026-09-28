"""Query-aware snippet extraction (§13) — spend the snippet budget on the relevant region.

WHY NOT `content[:600]`
----------------------
The snippet is by far the largest part of the judge payload (measured 2026-09-27: ~300 tokens of a
~453-token candidate question). Halving it by truncation is the cheapest possible change and also
the most dangerous: in this vault a note opens with frontmatter-ish prose and context, and the
sentence that actually answers the query frequently sits in the middle. A blind prefix cut removes
the evidence while keeping the boilerplate, so the judge sees a *less relevant* candidate and scores
it lower. That is not a token saving, it is a silent recall regression paid for with tokens.

WHAT THIS DOES
--------------
Score every line by query-term coverage, pick the best contiguous window under the budget, and
expand symmetrically around it until the budget is used. Structure is preserved: the section heading
is kept (it is cheap and strongly informative), code fences are not cut in half, and an elision
marker is inserted where text was removed so the judge can tell it is seeing an extract.

If the query has no usable terms, or nothing in the note matches, the function falls back to the
head of the note — the same behaviour as before, so there is never a worse-than-baseline case.

BUDGETS ARE A CEILING, NEVER A TARGET
-------------------------------------
Measured failure on the first implementation (2026-09-27): enabling smart snippets made the judge
payload BIGGER, not smaller — `snippet_tokens_saved = -415` over 24 candidates. The cause is that
extraction runs on the WHOLE note (it has to: the point is to reach a region a prefix cut never
contained), while the candidate's original snippet is a single heading-delimited SECTION, which is
frequently much shorter than the budget. Filling the budget then *added* text to candidates that were
already cheap.

So `extract` must be called with a budget that is `min(policy_budget, what_the_candidate_already_costs)`
and the caller must keep the original whenever extraction did not come out smaller. That rule lives in
`fit_or_keep` below so no call site can forget it.

`max_tokens` uses the project's deterministic estimator (chars/4 vs words*1.3), NOT a provider
tokenizer, so a snippet's cost is identical for every consumer and reproducible in benchmarks.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.gateway.token_budget import estimate_tokens, truncate_to_tokens
from app.services.query_fp import stem, tokens

SNIPPET_POLICY_VERSION = "snip-v1"
ELISION = "\n[…]\n"


@dataclass
class SnippetResult:
    text: str
    tokens: int
    strategy: str          # "focused" | "head" | "whole"
    matched_lines: int
    coverage: float        # fraction of query terms found anywhere in the note


def _line_scores(lines: list[str], qterms: set[str], qstems: set[str]) -> list[float]:
    """Per-line query coverage. An exact term hit outweighs a stem-only hit: the exact form is the
    stronger evidence, and identifiers ('asyncpg-0.31') only ever match exactly."""
    out: list[float] = []
    for line in lines:
        lt = tokens(line)
        if not lt:
            out.append(0.0)
            continue
        exact = len(qterms & set(lt))
        stemmed = len(qstems & {stem(t) for t in lt}) - exact
        out.append(exact * 1.0 + max(0, stemmed) * 0.4)
    return out


def _fence_mask(lines: list[str]) -> list[bool]:
    """True for lines inside a ``` fence (including the fence lines themselves)."""
    mask, inside = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            mask.append(True)
            inside = not inside
            continue
        mask.append(inside)
    return mask


def _cost(lines: list[str], lo: int, hi: int) -> int:
    return estimate_tokens("\n".join(lines[lo:hi]))


def extract(text: str, query: str, max_tokens: int, heading: str = "") -> SnippetResult:
    """Best contiguous window of `text` for `query`, within `max_tokens`."""
    if max_tokens <= 0 or not text.strip():
        return SnippetResult(text="", tokens=0, strategy="head", matched_lines=0, coverage=0.0)

    whole_cost = estimate_tokens(text)
    qt = set(tokens(query))
    qs = {stem(t) for t in qt}
    if whole_cost <= max_tokens:
        return SnippetResult(text=text, tokens=whole_cost, strategy="whole",
                             matched_lines=0, coverage=_coverage(text, qt))

    lines = text.split("\n")
    if not qt:
        cut = truncate_to_tokens(text, max_tokens)
        return SnippetResult(text=cut, tokens=estimate_tokens(cut), strategy="head",
                             matched_lines=0, coverage=0.0)

    scores = _line_scores(lines, qt, qs)
    fenced = _fence_mask(lines)
    if not any(scores):
        cut = truncate_to_tokens(text, max_tokens)
        return SnippetResult(text=cut, tokens=estimate_tokens(cut), strategy="head",
                             matched_lines=0, coverage=_coverage(text, qt))

    # Reserve room for the heading and the elision marker before choosing the window.
    prefix = f"{heading}\n" if heading and heading not in lines[0] else ""
    reserve = estimate_tokens(prefix) + estimate_tokens(ELISION) * 2
    budget = max(16, max_tokens - reserve)

    # Best seed line, then grow outwards while the budget allows, preferring the side whose next
    # line carries more query evidence (ties go downwards: explanations follow their topic).
    seed = max(range(len(lines)), key=lambda i: (scores[i], -i))
    lo, hi = seed, seed + 1
    # Never start or end inside a code fence: pull the boundary to the fence edge.
    while lo > 0 and fenced[lo] and fenced[lo - 1]:
        lo -= 1
    while hi < len(lines) and fenced[hi - 1] and fenced[hi]:
        hi += 1
    if _cost(lines, lo, hi) > budget:
        cut = truncate_to_tokens("\n".join(lines[lo:hi]), budget)
        return SnippetResult(text=prefix + cut, tokens=estimate_tokens(prefix + cut),
                             strategy="focused", matched_lines=1, coverage=_coverage(text, qt))

    while True:
        up_ok = lo > 0 and _cost(lines, lo - 1, hi) <= budget
        down_ok = hi < len(lines) and _cost(lines, lo, hi + 1) <= budget
        if not up_ok and not down_ok:
            break
        if up_ok and down_ok:
            if scores[lo - 1] > scores[hi]:
                lo -= 1
            else:
                hi += 1
        elif up_ok:
            lo -= 1
        else:
            hi += 1

    body = "\n".join(lines[lo:hi]).strip("\n")
    head_elided = ELISION if lo > 0 else ""
    tail_elided = ELISION if hi < len(lines) else ""
    out = f"{prefix}{head_elided}{body}{tail_elided}".strip("\n")
    if estimate_tokens(out) > max_tokens:
        out = truncate_to_tokens(out, max_tokens)
    matched = sum(1 for i in range(lo, hi) if scores[i] > 0)
    return SnippetResult(text=out, tokens=estimate_tokens(out), strategy="focused",
                         matched_lines=matched, coverage=_coverage(text, qt))


def _coverage(text: str, qterms: set[str]) -> float:
    if not qterms:
        return 0.0
    have = set(tokens(text))
    return round(len(qterms & have) / len(qterms), 4)


def fit_or_keep(full_text: str, current: str, query: str, budget: int,
                heading: str = "", min_saving: int = 0) -> tuple[str, str]:
    """Query-aware re-cut of `current` that is GUARANTEED not to grow it and not to lose evidence.

    This is the only entry point pipelines should use. It enforces four rules in one place:

      1. CEILING — the effective budget is capped by what the candidate already costs, so a cheap
         candidate can never be inflated to fill a larger policy budget.
      2. STRICT IMPROVEMENT — the result is kept only if it is cheaper by at least `min_saving`.
      3. NO EVIDENCE LOSS — the re-cut must not drop any query term that `current` already had.
      4. FAIL SAFE — on any doubt the original is returned unchanged, so the worst case equals the
         baseline exactly.

    WHY RULE 3 EXISTS (measured 2026-09-27, question sq070)
    -------------------------------------------------------
    Without it, smart snippets caused a real recall regression. The candidate's snippet was the note's
    `Resumo` section (66 tokens), which contained the answer token `granite-embed:278m-q23`. Extraction
    runs over the WHOLE note, so it was free to anchor its window on a DIFFERENT section, and it
    returned a 57-token window that no longer contained that token. It "saved" 9 tokens and the judge's
    verdict collapsed from 0.88 (KEEP) to 0.05 (DROP) — the note was dropped, recall for that question
    went 1.0 -> 0.0, and the pipeline reported it as a snippet optimization.

    Nine tokens is not a saving worth a recall loss, which is why rule 2 also enforces a minimum and
    rule 3 makes term loss disqualifying regardless of the size of the win.
    """
    current_cost = estimate_tokens(current)
    if current_cost <= 0:
        return current, "kept"
    effective = min(budget, current_cost)
    res = extract(full_text, query, effective, heading=heading)
    if not res.text:
        return current, "kept"
    if current_cost - res.tokens <= min_saving:
        return current, "kept"
    # Rule 3: every query term the CURRENT snippet already evidenced must survive the re-cut.
    qt = set(tokens(query))
    if qt:
        had = qt & set(tokens(current))
        kept = qt & set(tokens(res.text))
        if had - kept:
            return current, "kept_evidence_loss"
    return res.text, res.strategy
