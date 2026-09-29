"""Spike (items 1.5 + 5.7 of the 2026-09-28 proposal) — NOT wired into the pipeline.

Question: does a deterministic, "caveman"-style compression of the context text produced by
ModelContextBuilder (app/gateway/context_builder.py) save meaningful tokens without losing
verifiable facts, and without breaking the determinism the Memory Optimization Layer already
relies on for the consumer's prompt cache (same input -> same bytes, every time, no timestamps)?

Compression rule: strip PT/EN function words (articles, prepositions, conjunctions, pronouns,
auxiliary verbs) from prose. Never touch: code fences / inline code, <note source=...>...</note>
tags and their attributes, double-quoted literal strings, or any token that carries a digit or
starts with an uppercase letter (numbers, dates, proper nouns) -- those are never function words
in the removal list anyway, this is just belt-and-braces so the checker in this script has
something concrete to verify.

MG_MCP_RESPONSE=compact already exists (see app/mcp/server.py) and cuts ~73% off the MCP JSON
envelope (sources + most metrics) -- but it does NOT touch the `context` field's text. This spike
measures the caveman transform against real `context` text pulled from benchmark.db (read-only)
and reports it next to the compact-mode envelope saving, since they are different axes (envelope
vs. body) and both matter to the "what does the consumer actually pay for" question.

Usage:
    python scripts/spike_caveman_context.py [--db path] [--limit N]
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import statistics as st
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.gateway.token_budget import estimate_tokens  # noqa: E402

# -- function-word lists (PT + EN): articles, prepositions, conjunctions, pronouns, auxiliary verbs.
# Deliberately NOT exhaustive (this is a spike) -- see docs/SPIKE_CAVEMAN.md for the verdict.
STOPWORDS = {
    # PT articles / contractions
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "do", "da", "dos", "das", "no", "na", "nos", "nas",
    "ao", "aos", "à", "às", "pelo", "pela", "pelos", "pelas",
    "num", "numa", "duma", "dum",
    # PT prepositions
    "de", "em", "por", "para", "com", "sem", "sob", "sobre", "entre", "até",
    "desde", "contra", "perante", "após", "ante", "durante", "mediante", "conforme",
    # PT conjunctions / connectors
    "e", "ou", "mas", "porém", "contudo", "entretanto", "portanto", "logo", "pois",
    "que", "se", "quando", "enquanto", "como", "porque", "assim", "também", "já",
    "então", "ainda", "só", "apenas", "mais", "menos", "muito", "pouco",
    # PT pronouns
    "eu", "tu", "ele", "ela", "nós", "vós", "eles", "elas", "você", "vocês",
    "me", "te", "se", "lhe", "lhes", "nos", "vos", "isso", "isto", "aquilo",
    "meu", "minha", "meus", "minhas", "seu", "sua", "seus", "suas",
    "este", "esta", "estes", "estas", "esse", "essa", "esses", "essas",
    "aquele", "aquela", "aqueles", "aquelas", "qual", "quais", "quem", "cujo", "cuja",
    "algum", "alguma", "alguns", "algumas", "nenhum", "nenhuma", "todo", "toda", "todos", "todas",
    "outro", "outra", "outros", "outras",
    # PT auxiliary / copula verbs (finite forms, high frequency only)
    "é", "são", "foi", "foram", "era", "eram", "será", "serão", "seria", "seriam",
    "está", "estão", "estava", "estavam", "esteve", "estiveram", "ser", "estar",
    "tem", "têm", "tinha", "tinham", "teve", "tiveram", "ter", "haver", "há", "havia",
    "vai", "vão", "ia", "iam", "ir", "pode", "podem", "podia", "podiam",
    "deve", "devem", "devia", "deviam", "fazer", "faz", "fazem",
    # EN articles / prepositions
    "the", "a", "an", "of", "in", "on", "at", "by", "for", "with", "without",
    "to", "from", "into", "onto", "over", "under", "between", "among", "through",
    "about", "against", "during", "before", "after", "above", "below",
    # EN conjunctions
    "and", "or", "but", "so", "because", "if", "when", "while", "that", "as", "than",
    # EN pronouns
    "i", "you", "he", "she", "it", "we", "they", "him", "her", "them", "us",
    "my", "your", "his", "its", "our", "their", "this", "that", "these", "those",
    "who", "which", "whom", "whose",
    # EN auxiliary / copula verbs
    "is", "are", "was", "were", "be", "been", "being", "has", "have", "had",
    "do", "does", "did", "will", "would", "can", "could", "should", "must", "may", "might",
}

_PLACEHOLDER = "\x00{}\x00"
# Order matters: code fences before inline code (fences also contain backticks), tags before
# quotes (tag attributes are quoted), quotes last.
_PROTECT_PATTERNS = [
    re.compile(r"```.*?```", re.S),
    re.compile(r"</?note\b[^>]*>", re.S),
    re.compile(r"`[^`\n]+`"),
    re.compile(r'"[^"\n]{1,300}"'),
]
_WORD_STRIP = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def _protect(text: str) -> tuple[str, list[str]]:
    saved: list[str] = []

    def sub(pattern: "re.Pattern") -> None:
        nonlocal text

        def repl(m: "re.Match") -> str:
            saved.append(m.group(0))
            return _PLACEHOLDER.format(len(saved) - 1)

        text = pattern.sub(repl, text)

    for p in _PROTECT_PATTERNS:
        sub(p)
    return text, saved


def _restore(text: str, saved: list[str]) -> str:
    for i, original in enumerate(saved):
        text = text.replace(_PLACEHOLDER.format(i), original)
    return text


def caveman_compress(text: str) -> str:
    """Deterministic: identical input always produces identical output bytes."""
    if not text:
        return text
    protected, saved = _protect(text)
    out_lines = []
    for line in protected.split("\n"):
        kept = []
        for token in line.split(" "):
            if not token:
                kept.append(token)
                continue
            core = _WORD_STRIP.sub("", token)
            if core and core.isalpha() and core.lower() in STOPWORDS:
                continue  # drop the whole token, punctuation included
            kept.append(token)
        out_lines.append(" ".join(kept))
    compressed = "\n".join(out_lines)
    compressed = re.sub(r"[ \t]{2,}", " ", compressed)  # collapse gaps left by dropped tokens
    return _restore(compressed, saved)


# -- verification: every number/date/proper-noun token in the original must survive verbatim -----
_NUMBER_RE = re.compile(r"\d[\d.,:/\-]*\d|\b\d\b")
_PROPER_NOUN_RE = re.compile(r"\b[A-ZÀ-Ú][A-Za-zà-úÀ-Ú0-9_-]{2,}\b")


def extract_facts(text: str) -> set[str]:
    facts = set(_NUMBER_RE.findall(text))
    for m in _PROPER_NOUN_RE.findall(text):
        if m.lower() not in STOPWORDS:
            facts.add(m)
    return facts


def check_preservation(original: str, compressed: str) -> tuple[int, int, list[str]]:
    facts = extract_facts(original)
    missing = [f for f in facts if f not in compressed]
    return len(facts) - len(missing), len(facts), missing


def load_contexts(db: str, limit: int) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select run_id, pipeline, context from runs where context is not null "
        "and length(context) > 200 and (error is null or error='') "
        "order by length(context) desc limit ?",
        (limit,),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(PROJECT_ROOT / "benchmark.db"))
    ap.add_argument("--limit", type=int, default=200)
    a = ap.parse_args()

    rows = load_contexts(a.db, a.limit)
    if not rows:
        print("no contexts found in", a.db)
        return

    results = []
    determinism_failures = 0
    total_facts = 0
    total_missing_facts = 0
    all_missing: list[tuple[str, str]] = []
    t_total = 0.0
    for r in rows:
        ctx = r["context"]
        t0 = time.perf_counter()
        compressed = caveman_compress(ctx)
        t1 = time.perf_counter()
        compressed_again = caveman_compress(ctx)
        if compressed_again != compressed:
            determinism_failures += 1
        t_total += (t1 - t0)

        orig_tok = estimate_tokens(ctx)
        comp_tok = estimate_tokens(compressed)
        kept, total, missing = check_preservation(ctx, compressed)
        total_facts += total
        total_missing_facts += (total - kept)
        for m in missing[:3]:
            all_missing.append((r["run_id"], m))
        results.append({
            "run_id": r["run_id"], "pipeline": r["pipeline"],
            "orig_tokens": orig_tok, "comp_tokens": comp_tok,
            "saved_pct": round(1 - comp_tok / orig_tok, 4) if orig_tok else 0.0,
            "facts_total": total, "facts_kept": kept,
        })

    saved_pcts = [r["saved_pct"] for r in results]
    print("=" * 78)
    print("SPIKE — caveman compression of ModelContextBuilder context text")
    print("=" * 78)
    print(f"contexts sampled: {len(results)}  (largest {a.limit} by char length, from {a.db})")
    print(f"by pipeline: " + ", ".join(f"{p}={sum(1 for r in results if r['pipeline'] == p)}"
                                        for p in sorted({r['pipeline'] for r in results})))
    print()
    print("TOKENS SAVED (estimate_tokens, same heuristic the gateway itself uses)")
    print(f"  mean={st.mean(saved_pcts) * 100:.1f}%  median={st.median(saved_pcts) * 100:.1f}%  "
          f"min={min(saved_pcts) * 100:.1f}%  max={max(saved_pcts) * 100:.1f}%")
    total_orig = sum(r["orig_tokens"] for r in results)
    total_comp = sum(r["comp_tokens"] for r in results)
    print(f"  total: {total_orig:,} -> {total_comp:,} tokens ({(1 - total_comp / total_orig) * 100:.1f}% aggregate)")
    print()
    print("PROCESSING TIME")
    print(f"  total for {len(results)} contexts: {t_total * 1000:.1f} ms  "
          f"(mean {t_total / len(results) * 1000:.3f} ms/context)")
    print()
    print("DETERMINISM (same input compressed twice, byte-for-byte compare)")
    print(f"  failures: {determinism_failures}/{len(results)}")
    print()
    print("FACT PRESERVATION (every number/date/proper-noun token from the original)")
    print(f"  kept: {total_facts - total_missing_facts}/{total_facts} "
          f"({(total_facts - total_missing_facts) / total_facts * 100:.2f}%)" if total_facts else "  no facts extracted")
    if all_missing:
        print(f"  sample of missing (run_id, token), up to 10:")
        for run_id, tok in all_missing[:10]:
            print(f"    {run_id}  {tok!r}")
    print()
    print("REFERENCE — MG_MCP_RESPONSE=compact (existing, envelope only, does not touch `context`)")
    print("  measured in scripts/bench_optimizer.py mcp_transport: response JSON -73% "
          "(sources+metrics trimmed), context field itself is byte-identical to `full` mode.")
    print("  Caveman above compresses the context body itself -- an orthogonal, additive saving")
    print("  IF the fact-preservation and determinism checks above are clean.")


if __name__ == "__main__":
    main()
