# Memory Optimization Layer (MOL)

Operational guide for the layer that runs automatically inside **every** `MemoryGateway.search()`
call — MCP, REST, CLI, benchmark runner, and any future interface. Nobody has to remember to
invoke it; turning it off is the explicit action (`MG_OPTIMIZER=false`).

Code: `app/gateway/optimizer.py` · config: `config/optimizer.py` · tests: `tests/test_optimizer.py`
· benchmark: `scripts/bench_optimizer.py`.

## Flow

```
REQUEST (pipeline="auto" by default on MCP / REST / CLI)
  -> freshness       vault fingerprint (stat only) changed? -> rebuild lexical index, clear cache
  -> query analysis  canonical form + complexity class       (app/services/query_fp.py)
  -> result cache    same canonical query + scope + budget + vault version -> reuse (production only)
  -> routing         auto -> cheapest pipeline measured to hold recall (baseline for every class)
  -> retrieval       baseline | graphify | graphify_jev | graphify_jev_opt
  -> adaptive cut    SIMPLE/MEDIUM + free pipelines: drop score < 0.5 x best, keep >= 3
  -> near-dup        collapse copies / "-rev" / "-copia" notes (precision 1.000 @ 0.88)
  -> security flag   strong override phrases -> warning="possible-prompt-injection" on <note>
  -> context build   compact <note> headers
FINAL CONTEXT -> consumer model
```

Every stage is deterministic, local, **zero tokens**. The paid judge (JEV) is never called by the
layer; it remains available as an explicit pipeline.

## Measured impact (2026-09-28, `python scripts/bench_optimizer.py`, 0 API calls)

| corpus | context tokens before -> after | recall | facts in context | malicious notes unflagged |
| --- | --- | --- | --- | --- |
| synthetic, 520 notes, 120 q | 121,588 -> 73,349 (**-39.7%**) | 0.9136 -> 0.9136 | 102/110 -> 102/110 | 13 -> **0** |
| real vault, 86 notes, 12 q | 25,237 -> 19,121 (**-24.2%**) | 10/10 -> 10/10 | n/a | 0 -> 0 |

MCP transport per call (what an agent pays beyond the context itself):

| | tools | schema tokens / turn | response tokens (real vault) |
| --- | --- | --- | --- |
| before | 7 | 775 | 2,594 |
| after | 1 | 183 (**-76%**) | 710 (**-73%**) |

Zero questions regressed in either corpus. Latency rises from ~2.5 to ~5 ms (synthetic) and ~13 to
~20 ms (real vault) — the near-dup comparison — still two orders of magnitude below any model call.

## Switches (all in `.env`, restart to apply)

| variable | default | effect |
| --- | --- | --- |
| `MG_OPTIMIZER` | `true` | master switch; `false` = exact pre-layer behaviour |
| `MG_ROUTE_SIMPLE/MEDIUM/COMPLEX/AMBIGUOUS` | `baseline` | pipeline chosen by `auto` per query class |
| `MG_OPT_ADAPTIVE_CUT` | `true` | tail cut on SIMPLE/MEDIUM |
| `MG_OPT_CUT_RATIO` / `MG_OPT_CUT_FLOOR` | `0.5` / `3` | calibrated knee; first loss measured at 0.8 |
| `MG_OPT_NEAR_DEDUP` / `_THRESHOLD` | `true` / `0.88` | final-context near-duplicate collapse |
| `MG_OPT_COMPACT_HEADERS` | `true` | drop the section attribute when the block opens with that heading |
| `MG_OPT_INJECTION_FLAG` | `true` | add warning attribute; content never altered |
| `MG_OPT_RESULT_CACHE` / `_SIZE` / `_TTL_S` | `true` / `256` / `900` | in-process LRU; off in benchmark profile |
| `MG_VAULT_REFRESH_S` | `5` | seconds between vault fingerprint checks; `-1` = never |
| `MG_MCP_TOOLSET` | `minimal` | `full` re-exposes the 7 legacy tools |
| `MG_MCP_RESPONSE` | `compact` | `full` re-adds `sources` and the full metric set |

## Observability

Every run records, in `benchmark.db` (`runs.metrics_json`): `pipeline_requested`, `route_reason`,
`query_complexity`, `result_cache_hit`, `index_rebuilt`, `opt_adaptive_cut_removed`,
`opt_near_dup_removed`, `opt_injection_flagged`, `opt_snippet_tokens_removed`, `optimizer_version`
and `optimizer_errors` (stage failures; the request always continues). `GET /system/info` shows the
live cache hit rate and index rebuild count.

## Fallback guarantees

- Any stage exception -> recorded in `optimizer_errors`, candidates pass through unchanged.
- Graphify binary missing or `graphify update` failing -> `warm()` records the error and keeps
  serving; the default route never needed it.
- Invalid route in `.env` -> falls back to `baseline`.
- Result cache is keyed on the vault fingerprint and cleared on any change; stale answers cannot
  outlive a vault edit by more than `MG_VAULT_REFRESH_S` seconds.

## Hermes

Registered with the official CLI (`hermes mcp add`), one tool, real vault:

```
hermes mcp add memory-gateway --connect-timeout 60 \
  --env "MEMORY_GATEWAY_VAULT=C:\Users\<user>\Cérebro_AI" MG_MCP_TOOLSET=minimal MG_MCP_RESPONSE=compact \
  --command "<PROJECT_ROOT>\.venv\Scripts\python.exe" --args "<PROJECT_ROOT>\app\mcp\server.py"
hermes mcp test memory-gateway          # expect: Connected, Tools discovered: 1
hermes mcp remove memory-gateway        # rollback
```

## Evolving the layer (rules)

1. A new stage enters **off** or in shadow, gets a switch here, and must show in
   `scripts/bench_optimizer.py` that recall and facts-in-context do not drop on BOTH corpora.
2. Constants are calibrated with a sweep and set at the knee, not at the edge (document the sweep
   in the config comment).
3. Re-run `scripts/bench_optimizer.py --vault <real vault> --questions benchmark/questions.json`
   whenever the vault grows materially; the cut ratio and routing are measured on 86 real notes.
4. Promote a paid pipeline into an `auto` route only with a measured recall gain that pays for its
   `total_tokens_spent` — `context_reduction` alone is not evidence.
5. Bump `OPTIMIZER_VERSION` when a stage changes meaning (it is part of the result-cache key).
