"""Feature flags for every token optimization (§32). Default = BASELINE behaviour.

RULES THIS FILE ENFORCES
------------------------
1. Every optimization is off by default, so importing the project changes nothing.
2. `OptimizationConfig.baseline()` is frozen: it is the reference configuration that the 2026-09-27
   measurements were taken under, and benchmarks compare against it. It is never edited to look
   better — a new behaviour gets a new flag.
3. Anything that can change a routing decision starts in SHADOW mode (measure, do not serve):
   `cache_promote_l3`, `zero_evidence_drop`. Promotion is a flag flip backed by measured data.
4. Everything is overridable from the environment so a benchmark can sweep it without code edits.
"""
from dataclasses import dataclass, field, replace

from config import env_bool, env_float, env_int, env_str

# Bump when the MEANING of a flag changes (part of benchmark identity, not of the cache key).
OPTIMIZATION_VERSION = "opt-v1"


@dataclass
class OptimizationConfig:
    # -- master switch: False reproduces the pre-optimization pipeline exactly ------------------
    enabled: bool = field(default_factory=lambda: env_bool("OPT_ENABLED", False))

    # -- CAMADA A: fewer candidates reach the judge ---------------------------------------------
    near_dedup: bool = field(default_factory=lambda: env_bool("OPT_NEAR_DEDUP", False))
    # CALIBRATED 2026-09-27 (scripts/calibrate_heuristics.py, 60 declared duplicate groups + 120
    # control notes, pair-level precision/recall of the clustering):
    #     thr    collapsed   precision   recall      F1
    #     0.99          20      1.0000   0.3333   0.5000
    #     0.95          46      1.0000   0.7667   0.8679
    #     0.92          49      1.0000   0.8167   0.8991
    #     0.90          55      1.0000   0.9167   0.9565
    #     0.88          58      1.0000   0.9667   0.9831   <- chosen
    #     0.80..0.70    58      1.0000   0.9667   0.9831   (no further change)
    # Precision stays at 1.0000 down to 0.70 — zero false merges anywhere in the sweep — and recall
    # saturates at 0.88. Going lower buys nothing measurable, so 0.88 is the knee, not the edge: it
    # keeps the widest safety margin above the point where merges could start being wrong.
    near_dedup_threshold: float = field(default_factory=lambda: env_float("OPT_NEAR_DEDUP_THRESHOLD", 0.88))
    near_dedup_hamming: int = field(default_factory=lambda: env_int("OPT_NEAR_DEDUP_HAMMING", 12))
    adaptive_k: bool = field(default_factory=lambda: env_bool("OPT_ADAPTIVE_K", False))
    # HARD DEPENDENCY: adaptive_k REQUIRES early_stopping to be profitable, and `validate()` rejects
    # the combination adaptive_k=True, early_stopping=False.
    #
    # MEASURED 2026-09-27, 120 questions, isolated arms:
    #   baseline          120 requests,  937 questions -> 257,533 judge tokens
    #   adaptive_k alone  240 requests, 1000 questions -> 308,937 judge tokens  (+20.0%)
    #   adaptive_k+early  153 requests,  806 questions -> 237,178 judge tokens  (-7.9%)
    #
    # Why: with waves and no stop rule, the escalation fired on 120/120 queries (wave patterns were
    # (4,2) x100 and (16,4) x20 — never a lone (4,)). Every query therefore paid TWO requests to ask
    # the same questions one request could have carried, and a request costs 340 tokens = 1.6 candidate
    # questions (see app/services/jev.py). Waves only pay off when the escalation is usually NOT taken;
    # with the stop rule enabled it fired on 87/120 and the pattern became (4,) x77.
    #
    # This is the sharpest lesson of the whole round: splitting work into stages is not a saving, it is
    # a bet that the later stages will be skipped. Without the mechanism that skips them, it is a loss.
    # Escalation ceiling. 20, not 12: measured recall for COMPLEX/multi-hop queries was 0.500 at
    # K=8 and 0.833 at K=12, reaching 1.000 only at K=20 (worst answer position 18). A ceiling of 12
    # would have capped 3 of 18 complex questions below their answer's position — a guaranteed recall
    # loss that no judge behaviour could repair. See app/services/adaptive.py.
    adaptive_k_max: int = field(default_factory=lambda: env_int("OPT_ADAPTIVE_K_MAX", 20))
    early_stopping: bool = field(default_factory=lambda: env_bool("OPT_EARLY_STOPPING", False))
    # CALIBRATED 2026-09-27. The original default of 2 could NEVER be satisfied on this workload and
    # silently disabled early stopping entirely: the corpus (like the real vault) has ONE relevant
    # note per question, so `candidates_kept` was 0 or 1 in 5/5 measured queries and every wave check
    # returned "not_enough_strong". The mechanism appeared enabled, cost an extra request per query,
    # and bought nothing.
    #
    # 1 is safe here because the recall evidence does not come from the runtime score at all — it
    # comes from the calibration table in app/services/adaptive.py: for SIMPLE/MEDIUM queries the
    # deterministic ranker put every answer inside the top 3 (86/86). Stopping after a wave of 4 with
    # one confirmed KEEP therefore discards candidates that were already measured never to matter.
    # The remaining guards in `should_stop` (distance from the REVIEW band, and a decisive
    # deterministic gap to the best untried candidate) still have to pass.
    early_stop_min_strong: int = field(default_factory=lambda: env_int("OPT_EARLY_STOP_MIN_STRONG", 1))
    # Stop when the confirmed KEEP sits above this rank in the deterministic order. CALIBRATED over
    # 93 judged queries: the first KEEP landed at rank 0 (82x), 1 (2x) or 2 (9x) and NEVER deeper, and
    # the ground-truth note was never ranked deeper than the first KEEP (0/93). 3 = one position of
    # margin past the worst observed rank. Replaces a score-gap threshold that was measured to be a
    # constant 0.052 and therefore could never fire — see app/services/adaptive.py should_stop().
    early_stop_max_accept_rank: int = field(
        default_factory=lambda: env_int("OPT_EARLY_STOP_MAX_ACCEPT_RANK", 3))
    # SHADOW by default: measured, never served, until agreement with the judge is known (§21).
    zero_evidence_shadow: bool = field(default_factory=lambda: env_bool("OPT_ZERO_EVIDENCE_SHADOW", True))
    zero_evidence_drop: bool = field(default_factory=lambda: env_bool("OPT_ZERO_EVIDENCE_DROP", False))

    # -- CAMADA B: fewer repeated judgements ----------------------------------------------------
    layered_cache: bool = field(default_factory=lambda: env_bool("OPT_LAYERED_CACHE", False))
    cache_l2: bool = field(default_factory=lambda: env_bool("OPT_CACHE_L2", True))
    cache_l3_shadow: bool = field(default_factory=lambda: env_bool("OPT_CACHE_L3_SHADOW", True))
    cache_promote_l3: bool = field(default_factory=lambda: env_bool("OPT_CACHE_PROMOTE_L3", False))
    cache_ranking: bool = field(default_factory=lambda: env_bool("OPT_CACHE_RANKING", False))
    cache_snippets: bool = field(default_factory=lambda: env_bool("OPT_CACHE_SNIPPETS", False))

    # -- CAMADA C: less content per judgement ---------------------------------------------------
    # DOCUMENTED, NEVER WIRED (§5.5 item 3 / Parte 2b): `graphify_jev` (app.retrieval.pipelines) is
    # FROZEN and calls `dedup.preprocess` directly — it never reads `OptimizationConfig` at all, so
    # this flag cannot affect it no matter what it is set to. It exists only to record the intent
    # ("smart snippets could in principle apply to the frozen path too") without implying it is safe
    # or available; wiring it would require re-measuring the frozen baseline, which is out of scope.
    # Default False, and must stay False — there is no code path that reads this field.
    snippet_for_frozen: bool = field(default_factory=lambda: env_bool("OPT_SNIPPET_FOR_FROZEN", False))
    smart_snippet: bool = field(default_factory=lambda: env_bool("OPT_SMART_SNIPPET", False))
    snippet_tokens: int = field(default_factory=lambda: env_int("OPT_SNIPPET_TOKENS", 300))
    # Minimum tokens a re-cut must save to be worth taking. CALIBRATED 2026-09-27: on question sq070
    # a re-cut that saved NINE tokens (66 -> 57) dropped the answer token and flipped the judge from
    # 0.88 KEEP to 0.05 DROP, losing that question's recall entirely. The expected value of a tiny
    # win is negative: it is far below the 209-token cost of one candidate question, while the
    # downside is a whole answer. 40 tokens ≈ 20% of one candidate question — the smallest win that
    # is worth any risk at all.
    snippet_min_saving: int = field(default_factory=lambda: env_int("OPT_SNIPPET_MIN_SAVING", 40))
    progressive_context: bool = field(default_factory=lambda: env_bool("OPT_PROGRESSIVE_CONTEXT", False))
    # CALIBRATED 2026-09-27. The first-stage budget was 120, which made progressive context a net
    # loss: it shrank EVERY candidate up front, then paid an extra request (340 tokens, see
    # app/services/jev.py) to re-expand the one or two that landed near the threshold. A first stage
    # only pays for itself if the re-expansion is rare, so stage 1 now uses the normal snippet budget
    # and stage 2 exists purely to buy MORE context for genuine ambiguity — never to undo a cut this
    # same pipeline made.
    progressive_first_tokens: int = field(default_factory=lambda: env_int("OPT_PROGRESSIVE_FIRST_TOKENS", 300))
    progressive_second_tokens: int = field(default_factory=lambda: env_int("OPT_PROGRESSIVE_SECOND_TOKENS", 600))
    # Re-ask with more context only inside this band around the KEEP threshold (§14).
    progressive_band: float = field(default_factory=lambda: env_float("OPT_PROGRESSIVE_BAND", 0.12))

    # -- CAMADA D: strict mode only when it can matter ------------------------------------------
    strict_gating: bool = field(default_factory=lambda: env_bool("OPT_STRICT_GATING", False))
    strict_gate_on_relevance: bool = field(default_factory=lambda: env_bool("OPT_STRICT_GATE_RELEVANCE", True))
    strict_lexical_screen: bool = field(default_factory=lambda: env_bool("OPT_STRICT_LEXICAL_SCREEN", True))

    # -- CAMADA F: adaptivity / instrumentation -------------------------------------------------
    query_profiling: bool = field(default_factory=lambda: env_bool("OPT_QUERY_PROFILING", True))
    record_shadow_metrics: bool = field(default_factory=lambda: env_bool("OPT_RECORD_SHADOW", True))

    version: str = OPTIMIZATION_VERSION

    # ------------------------------------------------------------------------------------------
    @classmethod
    def baseline(cls) -> "OptimizationConfig":
        """The frozen reference configuration (§27). Never change these values."""
        return cls(enabled=False, near_dedup=False, adaptive_k=False, early_stopping=False,
                   zero_evidence_shadow=False, zero_evidence_drop=False, layered_cache=False,
                   cache_ranking=False, cache_snippets=False, smart_snippet=False,
                   progressive_context=False, strict_gating=False, query_profiling=False,
                   record_shadow_metrics=False)

    @classmethod
    def all_on(cls) -> "OptimizationConfig":
        """Every SAFE optimization on; the two shadow-only ones stay in shadow."""
        return cls(enabled=True, near_dedup=True, adaptive_k=True, early_stopping=True,
                   zero_evidence_shadow=True, zero_evidence_drop=False, layered_cache=True,
                   cache_l2=True, cache_l3_shadow=True, cache_promote_l3=False,
                   cache_ranking=True, cache_snippets=True, smart_snippet=True,
                   progressive_context=True, strict_gating=True, query_profiling=True,
                   record_shadow_metrics=True)

    @classmethod
    def default_cascade(cls) -> "OptimizationConfig":
        """Config `graphify_jev_opt` uses when an interface (REST/MCP/CLI/benchmark) calls it
        without an explicit `OptimizationConfig` (§1.3/§5.2 da proposta 2026-09-28). Every flag
        turned on here was independently calibrated and measured to be a net win (see the
        per-field comments above); the two flags this method leaves off stay off for the same
        reason `all_on()` leaves them off:

          - zero_evidence_drop: `validate()` VETOES this unconditionally — measured to flag 9
            ground-truth notes out of 1,419 candidates.
          - cache_promote_l3: requires L3 to have been measured in shadow mode first (§12); it is
            a promotion decision, not a default.

        Identical to `all_on()` today. Kept as a separate name because the two names answer
        different questions — `all_on()` is "every safe stage, for measurement/sweeps";
        `default_cascade()` is "what production serves when nobody configured anything" — and
        they are free to diverge later without moving `OptimizationConfig.baseline()`, which stays
        frozen (§27) regardless of what this method returns.
        """
        return cls.all_on()

    def with_(self, **kw) -> "OptimizationConfig":
        return replace(self, **kw)

    def validate(self) -> None:
        """Reject combinations that are measured to be net losses.

        This is not style enforcement — each rule here corresponds to a configuration that was
        actually run, cost real money, and made things worse. Failing loudly is cheaper than
        rediscovering it.
        """
        if not self.enabled:
            return
        if self.adaptive_k and not self.early_stopping:
            raise ValueError(
                "adaptive_k requires early_stopping: measured 2026-09-27, waves without a stop rule "
                "escalated on 120/120 queries and cost +20.0% judge tokens (308,937 vs 257,533) "
                "because a request costs 340 tokens. Enable early_stopping or disable adaptive_k."
            )
        if self.progressive_context and self.progressive_first_tokens < self.snippet_tokens:
            raise ValueError(
                f"progressive_first_tokens ({self.progressive_first_tokens}) must be >= "
                f"snippet_tokens ({self.snippet_tokens}): measured 2026-09-27, a first stage of 120 "
                "tokens shrank EVERY candidate up front and then paid an extra 340-token request to "
                "re-expand the 1-2 that landed near the threshold, which is a net loss. Stage 1 must "
                "use the normal snippet budget; stage 2 exists to buy MORE context for genuine "
                "ambiguity, never to undo a cut this same pipeline made."
            )
        if self.zero_evidence_drop:
            raise ValueError(
                "zero_evidence_drop is vetoed: measured 2026-09-27 it flagged 9 ground-truth notes "
                "out of 1,419 flagged candidates (graph-reachable notes sharing no vocabulary with "
                "the query). Use zero_evidence_shadow to keep measuring it."
            )
        if self.cache_promote_l3 and not self.cache_l3_shadow:
            raise ValueError(
                "cache_promote_l3 must not be enabled without having measured L3 in shadow mode "
                "first (§12): its false-positive rate is what justifies serving it."
            )

    def active_flags(self) -> list[str]:
        """Names of the OPTIMIZATION mechanisms actually in effect.

        Sub-options (cache_l2, strict_lexical_screen, ...) are excluded: they refine a mechanism but
        do nothing on their own, so listing them would make the frozen baseline look like it had
        optimizations enabled. Nothing is active at all when the master switch is off.
        """
        if not self.enabled:
            return []
        mechanisms = ("near_dedup", "adaptive_k", "early_stopping", "zero_evidence_drop",
                      "layered_cache", "cache_promote_l3", "cache_ranking", "cache_snippets",
                      "smart_snippet", "progressive_context", "strict_gating", "query_profiling")
        return [k for k in mechanisms if getattr(self, k) is True]

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# Bump when the MEANING of an optional-stage flag changes.
OPTIONAL_STAGES_VERSION = "stages-v1"

# Every name here must exist as a bool field below AND as a key in app.retrieval.optional_stages
# .STAGE_ORDER; app/retrieval/optional_stages.py asserts the two stay in sync.
OPTIONAL_STAGE_NAMES = ("llmlingua2", "provence", "bge_reranker_v2_m3", "mxbai_rerank_base_v2",
                        "sentence_dedup_mmr", "spotlight_nonce")

# -- APPROVED PRESET (M2 benchmark, docs/OPTIONAL_STAGES_BENCHMARK.md) ------------------------------
# A stage is approved only if it loses neither recall nor fact_in_context AND reduces total tokens or
# improves precision (rank-aware: P@3 / MRR), measured on the synthetic corpus (120 q) and the real
# vault (12 q) against the SAME baseline. Reprovados (llmlingua2, mxbai_rerank_base_v2,
# spotlight_nonce) keep their flag but are never part of a preset.
APPROVED_FREE_STAGES: tuple[str, ...] = ("sentence_dedup_mmr",)            # no model: safe to default ON
APPROVED_MODEL_STAGES: tuple[str, ...] = ("bge_reranker_v2_m3", "provence")  # heavy deps: opt-in only
APPROVED_STAGES: tuple[str, ...] = APPROVED_FREE_STAGES + APPROVED_MODEL_STAGES

# off      nothing: `graphify_jev_opt` exactly as before M2 (the comparable baseline)
# free     APPROVED_FREE_STAGES (default; needs no extra dependency)
# approved APPROVED_STAGES; a model stage whose library is missing is skipped + recorded (fallback)
STAGES_PRESETS = ("off", "free", "approved")
# The preset only touches the optimized judge path. `graphify_jev` is frozen; `baseline`/`graphify`
# only get the stages whose flag was set explicitly (env or config/local_settings.json).
PRESET_PIPELINES = ("graphify_jev_opt",)


def preset_stages(preset: str) -> tuple[str, ...]:
    return {"free": APPROVED_FREE_STAGES, "approved": APPROVED_STAGES}.get(preset, ())


@dataclass
class OptionalStagesConfig:
    """Feature flags for the optional retrieval stages evaluated in §1.4/§5.5 of the 2026-09-28
    proposal (`memory-gateway-token-optimization-audit.md` §13: LLMLingua-2, Provence,
    bge-reranker-v2-m3, mxbai-rerank-base-v2 as "experimentar"; sentence-dedup+MMR and
    spotlighting as no-model techniques from the same audit, §27 items 3 and 8).

    Independent of `OptimizationConfig` above (that one is the graphify_jev_opt cascade only,
    §1.3). These stages run for every pipeline EXCEPT `graphify_jev` (frozen reference — see
    app/retrieval/pipelines.py run_graphify_jev, never touched by this file), after candidate
    selection and before ModelContextBuilder (app/gateway/memory_gateway.py search()).

    Every flag is OFF by default (importing/running the project is unchanged). A stage whose
    dependency is not installed is skipped with ONE warning log line and
    `optional_stage_skipped:<name>` in the run metrics — never an exception (see
    app/retrieval/optional_stages.py).

    Rejected candidates (OmniRoute, RECOMP/Selective Context, GPTCache/RedisVL) have NO flag here
    on purpose — see config/optional_stages_catalog.py `REJECTED` for why.
    """
    # -- compression (shrinks a candidate's text) ------------------------------------------------
    llmlingua2: bool = field(default_factory=lambda: env_bool("OPT_STAGE_LLMLINGUA2", False))
    # naver/provence-reranker-debertav3-v1 -- LICENSE CC BY-NC-ND 4.0: personal / non-commercial
    # use only. Never enable this flag in a commercial deployment (config/optional_stages_catalog.py).
    provence: bool = field(default_factory=lambda: env_bool("OPT_STAGE_PROVENCE", False))

    # -- reranking (reorders candidates before the context budget cuts the tail) -----------------
    bge_reranker_v2_m3: bool = field(default_factory=lambda: env_bool("OPT_STAGE_BGE_RERANKER_V2_M3", False))
    mxbai_rerank_base_v2: bool = field(
        default_factory=lambda: env_bool("OPT_STAGE_MXBAI_RERANK_BASE_V2", False))

    # -- no model, deterministic, local -----------------------------------------------------------
    sentence_dedup_mmr: bool = field(default_factory=lambda: env_bool("OPT_STAGE_SENTENCE_DEDUP_MMR", False))
    # Jaccard similarity (word 3-shingles) above which two sentences are considered the same idea.
    # Reuses the near-duplicate threshold family calibrated in OptimizationConfig.near_dedup (0.88)
    # but one notch lower: sentence-level text is much shorter than a whole note, so the same wording
    # shift produces a bigger Jaccard swing (see app/services/near_dup.py module docstring, the
    # short-note-vs-long-note example). Not independently calibrated yet -- see
    # scripts/measure_optional_stages.py for the measurement this shipped with.
    sentence_dedup_mmr_threshold: float = field(
        default_factory=lambda: env_float("OPT_STAGE_SENTENCE_DEDUP_MMR_THRESHOLD", 0.85))
    # MMR trade-off inside a duplicate cluster: weight on relevance-to-query vs (1-lambda) weight on
    # redundancy-with-the-rest-of-the-cluster. 0.5 = no prior bias; see
    # app/retrieval/optional_stages.py sentence_dedup_mmr().
    sentence_dedup_mmr_lambda: float = field(
        default_factory=lambda: env_float("OPT_STAGE_SENTENCE_DEDUP_MMR_LAMBDA", 0.5))

    # -- model-stage tuning (only read when the matching stage is on) ------------------------------
    # LLMLingua-2 target keep-rate (fraction of tokens kept); upstream default 0.5.
    llmlingua2_rate: float = field(default_factory=lambda: env_float("OPT_STAGE_LLMLINGUA2_RATE", 0.5))
    # Provence keep-threshold on the per-sentence relevance; upstream default 0.1.
    # 0.05, not the upstream 0.1: at 0.1 Provence lost 1 of 110 buried facts on the synthetic corpus
    # (99/110 vs 100/110); 0.05 and 0.03 kept all 100 (docs/OPTIONAL_STAGES_BENCHMARK.md).
    provence_threshold: float = field(default_factory=lambda: env_float("OPT_STAGE_PROVENCE_THRESHOLD", 0.05))
    # Cross-encoder max input tokens (bounds VRAM/latency on long notes).
    rerank_max_length: int = field(default_factory=lambda: env_int("OPT_STAGE_RERANK_MAX_LENGTH", 1024))
    # Reranker score cache keyed by (stage, query_fp, text hash): a repeated question over unchanged
    # text never reaches the model.
    rerank_cache: bool = field(default_factory=lambda: env_bool("OPT_STAGE_RERANK_CACHE", True))

    spotlight_nonce: bool = field(default_factory=lambda: env_bool("OPT_STAGE_SPOTLIGHT_NONCE", False))
    # "hash" (default): nonce = sha256(content + local secret)[:12] -- deterministic, so identical
    # content always produces identical bytes (keeps the consumer's prompt cache AND this project's
    # own ResultCache, app/gateway/optimizer.py, working). "random": a fresh nonce every request --
    # stronger anti-injection signal (a note author cannot predict tomorrow's delimiter) but the
    # emitted context is byte-different every call, which defeats both caches. See
    # app/retrieval/optional_stages.py spotlight_nonce() docstring for the full trade-off.
    spotlight_nonce_mode: str = field(default_factory=lambda: env_str("OPT_STAGE_SPOTLIGHT_NONCE_MODE", "hash"))
    # Local secret mixed into the "hash" nonce. Empty by default (no secret configured yet); an
    # empty secret still produces a deterministic, content-derived nonce, it is just predictable by
    # anyone who can read the note content -- set OPT_STAGE_SPOTLIGHT_NONCE_SECRET to change that.
    spotlight_nonce_secret: str = field(
        default_factory=lambda: env_str("OPT_STAGE_SPOTLIGHT_NONCE_SECRET", ""))

    # OPT_STAGES_PRESET = off | free | approved (see STAGES_PRESETS). Unknown value -> "off".
    preset: str = field(default_factory=lambda: env_str("OPT_STAGES_PRESET", "free"))

    version: str = OPTIONAL_STAGES_VERSION

    def with_(self, **kw) -> "OptionalStagesConfig":
        return replace(self, **kw)

    def for_pipeline(self, pipeline: str) -> "OptionalStagesConfig":
        """Turn on the preset's stages when `pipeline` is one the preset applies to. Flags that are
        already True stay True; nothing is ever turned off here (config/local_settings.json is applied
        AFTER this, in `resolved`, so a user's explicit toggle always wins over the preset)."""
        if pipeline not in PRESET_PIPELINES:
            return self
        names = preset_stages(self.preset)
        return self.with_(**{n: True for n in names}) if names else self

    def active_flags(self) -> list[str]:
        return [n for n in OPTIONAL_STAGE_NAMES if getattr(self, n) is True]

    def resolved(self, pipeline: str | None = None) -> "OptionalStagesConfig":
        """Apply `config/local_settings.json` {"optional_stages": {"<name>": bool}} overrides so
        the frontend configuration page (proposta §1.4/§3) can toggle a stage without an env var
        or a restart. Only recognised stage names with an actual bool value override; the local
        file always wins over the env-derived default, same rule as
        config/optimizer.py verdict_enabled_default().
        """
        from config.local_settings import get_optional_stages

        base = self.for_pipeline(pipeline) if pipeline else self
        overrides = get_optional_stages()
        if not overrides:
            return base
        kw = {k: v for k, v in overrides.items() if k in OPTIONAL_STAGE_NAMES}
        return base.with_(**kw) if kw else base

    def to_dict(self) -> dict:
        return dict(self.__dict__)
