# Memory Gateway

**A retrieval gateway that measures what it costs you.**

Memory Gateway sits between an AI agent and a corpus of Markdown notes (an Obsidian vault,
a docs folder, any tree of `.md` files). It retrieves candidate passages, filters them with a
paid relevance judge (JEV), and hands the consumer model a small, clean context — while
recording, per query, exactly how many tokens the whole operation spent.

That last part is the point of the project. It is easy to build a retrieval filter that shrinks
the final context by 77% and costs ten times more in total, because the tokens moved from the
context into the filter. Memory Gateway is built to make that failure mode impossible to hide.

---

## 1. The problem

A naive RAG pipeline reports `context_reduction` and calls it a saving. It is not one. There are
three separate token budgets in play:

| Budget | Who pays | Usually reported? |
| --- | --- | --- |
| Retrieval candidates | nobody (local) | yes |
| **Judge / filter input** | **you, per query** | **often not** |
| Final context | you, per query, at the consumer model's price | yes |

A filter that cuts the context from 2,000 to 500 tokens looks like a 75% win. If it spent 20,000
judge tokens to decide that, the query got 10x more expensive. Every metric in this project is
therefore stated against **`total_tokens_spent = judge_tokens + context_tokens`**, and the headline
number is **`token_amplification = total_tokens_spent / context_tokens`** — how many tokens the
pipeline burns per token it actually delivers. Below 1.0 is impossible; the question is how close
you can get.

The optimization work in this repository is the attempt to push that ratio down **without losing
recall**, and the measurements of which attempts failed are kept alongside the ones that worked.

---

## 2. Concepts

**JEV** — the paid relevance judge. It returns calibrated probabilities only (never answers, never
routing decisions). `KEEP / REVIEW / DROP / QUARANTINE` are decided in code from those
probabilities, so the routing policy is auditable and can be re-applied to old runs at a different
threshold without paying again.

**The cascade.** Every free, deterministic stage runs first, and the judge only sees what the free
stages could not resolve:

```
  ALL CANDIDATES (BM25 body text + graph edges)
        │  scope filter, exact dedup, per-note cap          free
        ▼
  deterministic hybrid ranking                              free
        │  near-duplicate clustering (SimHash)              free
        │  zero-evidence flagging (shadow only)             free
        ▼
  adaptive top-K selection                                  free
        │  layered cache resolution (L1..L5)                free after first judgement
        ▼
  JEV relevance, in escalating waves                        PAID
        │  early stopping between waves                     saves PAID work
        │  progressive expansion, ambiguous minority only   PAID
        │  gated injection screening, suspicious only       PAID
        ▼
  verdict propagation to near-duplicates                    free
        ▼
  survivors → full note text → consumer context budget
```

**Near-duplicate clustering** — notes that are textually near-identical are judged once and the
verdict is propagated to the cluster. Measured on 60 declared duplicate groups: pair precision
1.0000, recall 0.9667, **zero false merges** at the chosen threshold of 0.88.

**Query-aware snippets** — instead of `content[:600]`, score each line by query-term coverage and
keep the best contiguous window. A blind prefix cut removes the evidence and keeps the
boilerplate, which lowers the judge's score: that is not a saving, it is a silent recall
regression paid for with tokens.

**Early stopping** — stop judging once the deterministic ranker's top candidate is confirmed
relevant. This is what makes wave-based judging profitable at all (see §7).

**Layered cache** — L1 exact, L2 normalized-term key, L3 query fingerprint (shadow), plus snippet
and ranking caches. Keys are namespaced so a benchmark arm can never read another arm's work.

---

## 3. Requirements

- **Python 3.14** (`requirements.txt` versions are pinned and verified against it)
- A **JEV / TypeSafe API key** — only needed for the pipelines that use the paid judge. The
  baseline pipeline, the whole test suite and the free-stage validator run without any key.
- Optional: [`graphify`](https://pypi.org/project/graphify/) CLI for graph extraction; the
  repository ships a pre-built graph for the example corpus, so it is not required to run anything
  here.
- Optional: Ollama / vLLM / Anthropic / OpenAI credentials for end-to-end consumer benchmarks.

---

## 4. Installation

```bash
git clone https://github.com/GabezFC/Memory_Gateway.git
cd Memory_Gateway

python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
```

Then edit `.env`. Nothing in it is required to run the tests or the free-stage validator.

---

## 5. Configuration

All configuration is environment-based; see `.env.example`, where every variable is documented.

### The vault

**The project has no hardcoded paths and works on any machine.** The corpus directory is resolved
with this precedence:

1. an explicit `--vault <path>` argument on any script that takes one
2. `MEMORY_GATEWAY_VAULT` in your environment or `.env`
3. `OBSIDIAN_VAULT_PATH` (legacy alias, still supported)
4. **the bundled example corpus** at `data/synthetic_vault`

Because of step 4, a fresh clone runs end to end with **zero configuration**. Absolute paths,
relative paths and `~` all work:

```bash
MEMORY_GATEWAY_VAULT=./data/synthetic_vault
MEMORY_GATEWAY_VAULT=/home/user/notes
MEMORY_GATEWAY_VAULT=C:/Users/YourUser/Documents/MyVault
```

A path that does not exist fails immediately with a message telling you which variable to set —
it never silently indexes an empty directory.

### The example corpus

`data/synthetic_vault` is **520 generated notes** with a machine-readable `MANIFEST.json`
declaring ground truth: 60 duplicate groups, 12 prompt-injection notes (6 malicious, 6 benign
decoys that merely *discuss* prompts), 60 archived notes and 140 planted facts. `benchmark/
synthetic_questions.json` holds **120 questions** with `expected_sources`, including deliberately
unanswerable ones so hallucination is measurable.

This corpus is what makes the benchmark reproducible by a stranger. It contains no personal data.

---

## 6. Running

```bash
# REST API + dashboard on http://127.0.0.1:8000
python -m app.main

# one search from the CLI (pipeline defaults to "auto" = optimization layer)
python -m memory_gateway search "your question" --show-context

# before/after benchmark of the optimization layer (0 API calls)
python scripts/bench_optimizer.py

# rebuild the mirror and graph for your own vault
python -m memory_gateway index

# prove the vault was never written to
python -m memory_gateway vault-check --save before.json
python -m memory_gateway vault-check --compare before.json   # exit 1 if any .md changed
```

### Tests

```bash
python -m pytest tests/ -q
```

No network, no API key, no paid calls — JEV, Graphify, the providers and the agents are all faked.

### Free-stage validation (0 API calls)

```bash
python scripts/validate_free_stages.py
```

Validates every deterministic stage against the corpus manifest's ground truth: duplicate
clustering precision/recall, cache-key behaviour across paraphrases, injection screening,
retrieval recall@K, adaptive-K safety versus the real answer position, and the zero-evidence rule.
Runs in seconds and costs nothing. **Run this before spending money on a benchmark.**

### The optimization benchmark (spends real tokens)

```bash
python scripts/bench_optimizations.py \
  --vault ./data/synthetic_vault \
  --arms all \
  --two-pass \
  --out reports/opt_stack_v2.json
```

Use `--dry-run` to plan without calling the API, `--limit N` to cap questions, and `--arms
baseline,full_stack` to run a subset.

---

## 7. Benchmark methodology

Three properties make the numbers trustworthy, and each exists because its absence produced a
wrong result that was believed for a while.

**The baseline arm is frozen and always runs first.** `OptimizationConfig.baseline()` is never
edited to look better; a new behaviour gets a new flag. Every other arm is compared against it on
the same questions in the same order.

**Cache isolation is per-arm by default.** The first run of this benchmark had the baseline
reporting *zero* judge tokens on three questions and winning by 2x — it was reading judgements
cached by an earlier smoke run. Comparing a warm arm against a cold one measures run order, not
optimization. `--isolation arm` gives every arm its own namespace so its cost is attributable to
its own mechanisms.

**Cache arms are measured over two passes.** A cache's entire value is amortization, so pass 1 is
cold (pays full price, populates) and pass 2 replays the questions including paraphrases. Both
figures are reported; the headline is always the **cold** one. Reporting only the warm pass would
be dishonest, reporting only the cold pass would claim caches are useless.

**Recall is measured on the delivered context**, not on the candidate pool. A note the judge kept
but the context builder dropped for budget reasons was not delivered. Any token saving that pushes
a relevant note out of the context is counted as a recall loss, wherever it happened.

---

## 8. Results

> **Status of every number below: measured on the 520-note synthetic corpus over 120 questions,
> with the paid judge, after the correctness fixes described in §9.** Results from before those
> fixes have been discarded, not re-labelled — see the warning at the end of this section.

### Free stages (deterministic, 0 API calls, reproducible by anyone)

| Stage | Result | Verdict |
| --- | --- | --- |
| Near-duplicate clustering | pair precision **1.0000**, recall 0.9667, 0 false merges | safe |
| Injection screening | catches **6/6** malicious notes; flags 47.9% of ordinary notes | safe as a *gate*, unusable as a filter |
| L3 query-fingerprint cache | 20/20 paraphrase pairs matched, 0 unexpected collisions | shadow only |
| Adaptive-K plans vs. real answer position | **0** unsafe plans out of 120 | safe |
| Zero-evidence rule | flags 48.8% of candidates — but **9 of them are ground truth** | **shadow only, never promoted** |

The zero-evidence row is the one worth reading twice: a rule that drops 48.8% of candidates for
free looks extremely attractive, and it would have silently destroyed recall on 9 questions. It is
implemented, measured every run, and deliberately never allowed to serve.

### Optimization stack (paid, 120 questions, cold pass = attributable cost)

Each arm adds exactly one mechanism to the one above it, so a difference between consecutive rows
is attributable to that mechanism. `judge` is the cold pass; `warm` is the same arm replayed with
its cache populated. **`regr` is the number of questions whose recall got worse than baseline.**

| arm | judge tokens | vs baseline | warm | context | total | amp | recall | req | regr |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline` (frozen) | 257,533 | — | — | 57,936 | 315,469 | 5.45 | 0.900 | 120 | — |
| `01_profiling_shadow` | 257,533 | +0.0% | — | 57,783 | 315,316 | 5.46 | 0.900 | 120 | **0** |
| `02_near_dedup` | 257,375 | −0.1% | — | 57,966 | 315,341 | 5.44 | 0.900 | 120 | **0** |
| `03_layered_cache` | 262,697 | +2.0% | **0** | 55,999 | 318,696 | 5.69 | 0.900 | 120 | **0** |
| `04_adaptive_k_early_stop` | 237,926 | **−7.6%** | 71,011 | 56,955 | 294,881 | 5.18 | 0.900 | 154 | **0** |
| `05_smart_snippet` | **237,237** | **−7.9%** | 71,685 | 56,672 | 293,909 | 5.19 | 0.900 | 153 | **0** |
| `06_progressive` | 243,193 | −5.6% | 77,641 | 56,629 | 299,822 | 5.29 | 0.900 | 160 | **0** |
| `07_strict_gating` | 243,644 | −5.4% | 76,596 | 55,999 | 299,643 | 5.35 | 0.900 | 161 | **0** |
| `full_stack` | 242,190 | −6.0% | 76,638 | 56,045 | 298,235 | 5.32 | 0.900 | 159 | **0** |

**How to read this.**

*The best arm saves 7.9% of judge tokens and zero recall.* Mean recall is 0.900 on every single
arm — identical to the baseline — and no arm regressed a single question. Routing agreement with
the baseline stays between 0.947 and 0.994.

*Adding more mechanisms is not monotonically better.* The stack peaks at `05_smart_snippet` and
then gets **worse**: progressive context and strict gating each add requests (153 → 160 → 161) and
give the tokens back. They are kept in the codebase, measured every run, and are **not** part of
the recommended configuration.

*The cache dominates everything else, but only on repeat traffic.* The warm pass costs 71,011
tokens against 237,926 cold — a **70% saving** — and `03_layered_cache`'s warm pass is literally
**0** judge tokens. On first contact the same arm costs **+2.0%** (it pays to populate). A cache is
worth exactly as much as your query repetition rate, and this benchmark reports both ends of that
honestly instead of picking the flattering one.

*Amplification barely moves* (5.45 → 5.18). This corpus answers most questions from one short note,
so the context is small and the judge's fixed per-request cost dominates. The floor for one query
is ~549 tokens, which is why a 7.9% judge saving only shifts the ratio slightly.

**Leak invariant — the check that makes these numbers trustworthy:**

| arm | candidates sent | routed | UNSELECTED | accounting closes |
| --- | ---: | ---: | ---: | :---: |
| `baseline` | 960 | 960 | 0 | ✅ |
| `04_adaptive_k_early_stop` | 1,000 | 1,000 | **192** | ✅ |
| `full_stack` | 1,000 | 1,000 | **194** | ✅ |

The optimized arms deliberately refuse to pay for ~194 candidates, those candidates are now
*visible* in the report, and context tokens stayed at **56,045 vs the baseline's 57,936**. Compare
that with the contaminated run, where the same 194 candidates leaked into the context and pushed it
to **117,196**. Every arm sums to exactly the number of candidates it sent — a benchmark that
cannot prove this is not auditable.

### The cost model, re-measured

The previously recorded fit was `tokens ≈ 340 × requests + 209 × questions` with ~0.3% error.
**That error figure does not reproduce on this run.** Measured against all nine arms:

| arm | predicted | actual | error |
| --- | ---: | ---: | ---: |
| `baseline` | 236,633 | 257,533 | **+8.1%** |
| `04_adaptive_k_early_stop` | 221,232 | 237,926 | **+7.0%** |
| `full_stack` | 223,768 | 242,190 | **+7.6%** |

The model **underestimates by 7–8% consistently**, so its *shape* holds (requests and questions are
the right variables, and the relative cost of a request versus a question is unchanged) but its
constants are fitted to a smaller sample than this one. The structural conclusions that depend only
on the ratio — an extra request costs ~1.6 candidate-questions; stage-splitting is a bet on
skipping later stages — are unaffected. The absolute constants should be re-fitted before being
quoted as precise.

### ⚠ Superseded results

An earlier report (`reports/opt_stack_FINAL.json`) circulated a **−3.0%** headline for the full
stack. **That number is invalid and must not be cited.** Two defects contaminated it:

1. **Context leak.** Candidates the optimizer deliberately chose *not* to pay for were marked
   `UNJUDGED` rather than `UNSELECTED`, and the default `fail_open` policy let them into the
   delivered context. 194 such candidates accounted for 60,534 tokens — **51.7% of that arm's
   entire context** — doubling context tokens (58,219 → 117,196) versus the baseline while the arm
   reported a judge-token saving. The optimization was moving cost from the judge to the consumer
   model and calling it a win.
2. **Recall regression.** A snippet re-cut that saved nine tokens dropped the answer token on one
   question, flipping the judge from 0.88 `KEEP` to 0.05 `DROP` and taking that question's recall
   from 1.0 to 0.0.

Both are fixed, and both now have regression tests that were **verified to fail when the fix is
reverted** — a test that cannot detect the bug it names is decoration. The benchmark additionally
enforces a leak invariant (`routing_accounts_for_all_candidates`) so the accounting must close on
every future run. The dashboard labels results `Verified` / `Experimental` / `Invalid – superseded`
so a discarded number cannot quietly return.

---

## 9. What was measured and rejected

These are kept deliberately. A rejected optimization that is not written down gets re-implemented.

**Hoisting the judge's static criteria.** The relevance criteria are re-sent with every candidate:
82 tokens × ~50 candidates ≈ 4,100 tokens per query of pure repetition, and the SDK allows
declaring them once in `state`. Tested against the real API: input fell 3,814 → 2,971 (**−22.1%**)
— **and the judgement changed.** A ground-truth note moved 0.79 `KEEP` → 0.75 `REVIEW`, 2 of 12
routing decisions flipped, mean |Δ| 0.08. The per-question criteria are part of what the judge
evaluates, not framing that can be hoisted. **Not adopted.**

**Adaptive-K without early stopping.** Waves alone cost **+20.0%** (308,937 vs 257,533 judge
tokens): with no stop rule the escalation fired on 120/120 queries, so every query paid two
requests to ask what one request could have carried. A request costs ~340 tokens ≈ 1.6 candidate
questions. With early stopping enabled the same mechanism became a **−7.9%** saving.
`OptimizationConfig.validate()` now *rejects* the combination outright.

> This is the sharpest lesson in the project: **splitting work into stages is not a saving, it is
> a bet that the later stages will be skipped.** Without the mechanism that skips them, it is a
> loss.

**A smaller first stage for progressive context.** Shrinking every candidate to 120 tokens up
front, then paying an extra request to re-expand the one or two that landed near the threshold,
measured as a net loss. Stage 1 now uses the normal budget; stage 2 exists only to buy *more*
context for genuine ambiguity, never to undo a cut this same pipeline made.

**Min-max normalization in the pre-filter.** Gave 1.0 to every tied candidate, letting 29
irrelevant notes outrank the one whose name matched the query. Caught by a unit test; now uses
rank percentile with tie mediation.

### The cost model

Least-squares fit over real requests on this corpus:

```
input_tokens ≈ 340 × REQUESTS + 209 × QUESTIONS        (residuals within ±136 on 1,800–2,600)
```

Three consequences drive every design decision in `app/services/jev.py`:

1. An extra request costs ~1.6 candidate-questions, so waves must usually *not* escalate.
2. Halving the candidate count does not halve the cost (8→4 candidates is −42%, not −50%).
3. The floor for one query is ~549 tokens. Any amplification target must be stated against that
   floor, not against zero.

---

## 10. Project structure

```
app/
  main.py            FastAPI app (REST + dashboard)
  gateway/           MemoryGateway: routing, context building, metrics, persistence
  retrieval/         pipelines.py (frozen baseline) · pipelines_opt.py (the cascade)
  services/          jev.py · snippet.py · near_dup.py · jev_cache.py · adaptive.py
                     prefilter.py · injection_screen.py · query_fp.py · obsidian.py
  api/ mcp/ cli/     REST routes · MCP stdio server · command line
  adapters/agents/   consumer adapters (isolated; nothing in core depends on them)
config/              retrieval.py · jev.py · optimization.py · pricing.py · benchmark.py
scripts/             bench_optimizations.py · validate_free_stages.py · audit_pipeline.py
                     gen_synthetic_corpus.py · calibrate_heuristics.py
tests/               282 tests, no network, no keys
data/synthetic_vault/  520-note example corpus + MANIFEST.json ground truth
benchmark/           synthetic_questions.json (120 questions)
frontend/            dashboard (vanilla ES modules, no build step)
docs/                ENVIRONMENT.md · JEV_API.md
```

Two pipelines live side by side permanently: `pipelines.py` is the **frozen baseline** and
`pipelines_opt.py` is the cascade. The baseline is never edited to improve a comparison.

---

## 11. Interfaces

Every interface defaults to `pipeline="auto"`: the **Memory Optimization Layer** runs on every
search (routing, result cache, index freshness, adaptive cut, near-duplicate collapse, injection
flag, compact headers — all zero-token). Measured: context **-39.7%** (synthetic, 520 notes) and
**-24.2%** (real vault) with recall unchanged. See [`docs/OPTIMIZATION_LAYER.md`](docs/OPTIMIZATION_LAYER.md).

**MCP (preferred for agents)** — `python -m app.mcp.server`, stdio. Default toolset is **one tool**,
`memory_search(query, pipeline="auto", max_results, scope)` with a compact response (schemas cost
183 instead of 775 tokens per turn). `MG_MCP_TOOLSET=full` restores the read-only legacy set:
`memory_search_baseline`, `memory_search_graphify`, `memory_search_graphify_jev`,
`memory_benchmark`, `memory_get_run`, `memory_stats`.

**REST** — `GET /health` · `POST /memory/search[/{baseline,graphify,graphify-jev}]` ·
`POST /benchmark/{run,run-all,estimate,threshold-sweep}` · `GET /benchmark/{runs,sessions,stats}` ·
`POST /feedback/*` · `GET /system/{info,integrations,projects}`. Interactive docs at `/docs`.

**CLI** — `python -m memory_gateway {search,benchmark,sweep,stats,info,index,vault-check}`.

Retrieved note content is **data, not instruction**. Consumers must never follow commands found
inside retrieved notes; the injection screen and `QUARANTINE` routing exist for exactly this.

### Scoping

Projects and areas are discovered from vault paths — no names are hardcoded. Every search accepts
a `scope`, applied *before* the judge (a narrow scope costs fewer tokens) and re-applied before
building the context (defence in depth against cross-project leakage):

```bash
curl -X POST localhost:8000/memory/search/baseline \
  -H "Content-Type: application/json" \
  -d '{"query":"database driver decision","scope":"projeto:myproject"}'
```

---

## 12. Security and privacy

- **Never commit `.env`.** It is gitignored; `.env.example` ships with fictional placeholders.
- **The vault is read-only in code, not by convention.** All access goes through
  `app/services/obsidian.py`, which validates that the path is inside the configured vault and
  that the operation is in `READ_ONLY_OPERATIONS = {list, read, stat, hash}`. There is no write
  function. `vault-check` proves it by hashing every `.md` before and after.
- **Nothing derived from a private vault is published.** `data/`, `logs/`, `reports/`,
  `benchmark.db` and `benchmark/questions.json` are all gitignored. Only the synthetic corpus and
  `benchmark/questions.example.json` are versioned.
- **Do not publish your own vault or its benchmark dataset.** A question file built from a real
  vault contains real names, business decisions and note paths.
- API keys are read from the environment only and are never logged, echoed, or persisted into
  `benchmark.db`.

---

## 13. Limitations

- **The paid pipeline is not the default for a reason.** On this corpus the baseline retriever
  still delivers excellent recall at zero token cost and millisecond latency. `graphify_jev` is
  worth its price when precision matters more than cost, not universally.
- **Results are measured on a synthetic corpus.** It was generated to have known ground truth, and
  its duplicate/injection/fact distribution is deliberate rather than natural. Real vaults differ;
  validate on your own corpus before trusting a number.
- **Judge scores are not calibrated to your domain.** Measured here, the judge scores some
  *correct* notes 0.07–0.40, which is why `JEV_MIN_SURVIVORS` (a safety net returning top
  retrieval candidates when the judge eliminates everything) exists at all.
- **The injection screen over-flags.** 47.9% of ordinary notes trip it. It is safe as a gate that
  decides who gets a paid injection question; it would be destructive as a filter.
- **Graph retrieval alone cannot find body text.** The graph indexes labels (filenames, headings)
  only, so answers living in a note's body are unreachable by graph traversal at any budget. This
  is why retrieval is hybrid BM25 + graph rather than graph-only.
- **`retry_count` is unavailable** — the SDK does not expose retry attempts. It is reported as
  `null`, never estimated.

Unknown values are reported as `null` throughout. Nothing is estimated and presented as measured.

---

## 14. Status

| Area | Status |
| --- | --- |
| Test suite (282 tests) | **Verified** — passing, no network, no keys |
| Free-stage validation | **Verified** — reproducible by anyone, 0 API calls |
| Near-dedup, cache keys, injection gate, adaptive-K safety | **Verified** against corpus ground truth |
| Optimization stack cost/recall (§8) | **Verified** — 120 questions, paid judge, leak invariant closes on every arm |
| Context-leak fix (`UNSELECTED`) | **Verified** — 194 skipped candidates accounted for, context 56,045 vs 117,196 contaminated |
| Recall-regression fix (`fit_or_keep`) | **Verified** — 0 regressed questions across all 9 arms |
| Cost-model constants (340 / 209) | **Experimental** — shape holds, constants underestimate by 7–8% on this sample |
| Zero-evidence drop rule | **Shadow only** — measured unsafe (flags 9 ground-truth notes), never promoted |
| L3 cache promotion | **Shadow only** — awaiting a false-positive rate that justifies serving it |
| Cache hit rate in production | **Not yet validated** — benchmark measures cold/warm, not real repetition rate |
| Real-vault validation | **Not yet validated** — integration/robustness only; never mixed with synthetic numbers |
| Consumer end-to-end benchmark | **Experimental** |
| OpenCode adapter | **Not validated** — no credentials available |

---

## 15. License

MIT — see [`LICENSE`](LICENSE).
