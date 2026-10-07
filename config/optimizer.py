"""Automatic Memory Optimization Layer configuration (runs on EVERY MemoryGateway.search call).

This is deliberately separate from config/optimization.py:
  - config/optimization.py  = flags of the experimental paid-judge cascade (`graphify_jev_opt`),
                              all OFF by default, frozen baseline for benchmarks.
  - config/optimizer.py     = the ALWAYS-ON layer that sits between every retrieval pipeline and
                              the consumer model. Every stage here is deterministic, local, costs
                              zero tokens, and was measured before being turned on (see
                              scripts/bench_optimizer.py and the vault note
                              `memory-gateway-token-optimization-audit`).

Every stage has its own switch so a regression can be isolated and rolled back without a deploy:
set the variable in .env and restart. `MG_OPTIMIZER=false` disables the whole layer and restores
the exact pre-2026-09-28 behaviour (the default pipeline stays whatever the caller asked for).
"""
import json
from dataclasses import dataclass, field, replace

from config.paths import local_settings_path
from config import PROJECT_ROOT, env_bool, env_float, env_int, env_str  # noqa: F401  (PROJECT_ROOT re-exported)

# Part of the result-cache key and of every run's metrics. Bump when a stage changes MEANING.
# mol-v2 (2026-10-02): provenance lines, temporality (supersession/archived) and conflict demotion
# joined the layer, so the same query over the same vault now delivers a different context.
OPTIMIZER_VERSION = "mol-v2"

ROUTE_TARGETS = ("baseline", "graphify", "graphify_jev", "graphify_jev_opt")

# User-local, gitignored (never committed, never read from the vault). Same file the future
# frontend toggle (proposta 2026-09-28 §3) is meant to write to — "config local (arquivo), não no
# vault". Missing or malformed file is not an error: every key is optional.
LOCAL_SETTINGS_PATH = local_settings_path()


def _local_settings() -> dict:
    try:
        return json.loads(LOCAL_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}


def verdict_enabled_default() -> bool:
    """MG_VERDICT_ENABLED env, overridden by config/local_settings.json {"verdict_enabled": bool}.

    The local file wins when the key is present and is actually a bool -- anything else (missing
    file, missing key, wrong type) falls back to the env var, which defaults to False (§1.2:
    "default a decidir após validação" -- the 2026-09-29 benchmark never found a scope where a
    non-baseline pipeline was worth it, see docs/SCOPE_BENCHMARK.md, so there is nothing validated
    to turn on by default yet).
    """
    local = _local_settings().get("verdict_enabled")
    if isinstance(local, bool):
        return local
    return env_bool("MG_VERDICT_ENABLED", False)


@dataclass
class OptimizerConfig:
    # -- master switch --------------------------------------------------------------------------
    enabled: bool = field(default_factory=lambda: env_bool("MG_OPTIMIZER", True))

    # -- ROUTING: pipeline="auto" picks the cheapest pipeline measured to hold recall -----------
    # Measured 2026-09-28 (synthetic corpus, 520 notes, 110 answerable questions) and 2026-09-27
    # (real vault, 10 answerable questions): baseline and graphify tie on recall in every query
    # class, baseline costs zero tokens and needs no graph.json. The paid judge never beat them
    # on recall. So every class routes to baseline by default; each class stays overridable.
    route_simple: str = field(default_factory=lambda: env_str("MG_ROUTE_SIMPLE", "baseline"))
    route_medium: str = field(default_factory=lambda: env_str("MG_ROUTE_MEDIUM", "baseline"))
    route_complex: str = field(default_factory=lambda: env_str("MG_ROUTE_COMPLEX", "baseline"))
    route_ambiguous: str = field(default_factory=lambda: env_str("MG_ROUTE_AMBIGUOUS", "baseline"))

    # -- ADAPTIVE CUT: drop the long tail whose retrieval score is far below the best hit --------
    # Only for SIMPLE/MEDIUM queries on the FREE pipelines (the judge already selected on its own).
    # Keeps at least `cut_floor` results so the top of the ranking is never touched.
    #
    # CALIBRATED 2026-09-28 (sweep ratio x floor, zero API calls):
    #   synthetic 520 notes / 110 answerable   recall 0.9136 and facts 102/110 IDENTICAL for every
    #       ratio <= 0.7 at any floor; ratio 0.8 loses 2-3 questions (first loss = the edge).
    #   real vault 86 notes / 10 answerable    10/10 at every point of the sweep.
    #   context tokens (synthetic, floor 3): 0.3 -> 99.5k, 0.5 -> 73.3k, 0.7 -> 62.8k (no cut: 121.6k)
    # 0.5 / floor 3 is chosen as the KNEE, two steps below the first measured loss — the same rule
    # used for near_dedup_threshold in config/optimization.py. Do not raise toward 0.7 without
    # re-running scripts/bench_optimizer.py on a larger vault: the margin is the point.
    adaptive_cut: bool = field(default_factory=lambda: env_bool("MG_OPT_ADAPTIVE_CUT", True))
    cut_ratio: float = field(default_factory=lambda: env_float("MG_OPT_CUT_RATIO", 0.5))
    cut_floor: int = field(default_factory=lambda: env_int("MG_OPT_CUT_FLOOR", 3))

    # -- NEAR-DUPLICATE collapse of the FINAL context (copies, "-rev", "-copia" notes) ----------
    # Reuses the clusterer calibrated for the judge cascade (precision 1.000 at 0.88).
    near_dedup: bool = field(default_factory=lambda: env_bool("MG_OPT_NEAR_DEDUP", True))
    near_dedup_threshold: float = field(default_factory=lambda: env_float("MG_OPT_NEAR_DEDUP_THRESHOLD", 0.88))

    # -- COMPACT note headers (section attr = last heading only, capped) -------------------------
    compact_headers: bool = field(default_factory=lambda: env_bool("MG_OPT_COMPACT_HEADERS", True))
    header_section_max_chars: int = field(default_factory=lambda: env_int("MG_OPT_HEADER_SECTION_CHARS", 60))

    # -- SECURITY: flag (never drop) notes with strong instruction-override phrases --------------
    # Free pipelines had NO injection check: 13/120 synthetic queries delivered a malicious note
    # unmarked. The flag is an attribute on the <note> block; content is untouched.
    injection_flag: bool = field(default_factory=lambda: env_bool("MG_OPT_INJECTION_FLAG", True))

    # -- RESULT CACHE: identical (normalized) request + unchanged vault -> reuse -----------------
    # Only active when the runtime profile enables caching (production); benchmarks force it off.
    result_cache: bool = field(default_factory=lambda: env_bool("MG_OPT_RESULT_CACHE", True))
    cache_size: int = field(default_factory=lambda: env_int("MG_OPT_CACHE_SIZE", 256))
    cache_ttl_s: float = field(default_factory=lambda: env_float("MG_OPT_CACHE_TTL_S", 900.0))

    # -- FRESHNESS: rebuild the lexical index when the vault changes ------------------------------
    # Seconds between vault fingerprint checks (stat only, ~8 ms for 90 notes, ~33 ms for 520).
    # 0 = check on every call; negative = never (old behaviour: index frozen at startup).
    refresh_interval_s: float = field(default_factory=lambda: env_float("MG_VAULT_REFRESH_S", 5.0))

    # -- VERDICT: routing decision for pipeline="auto", backed by docs/SCOPE_BENCHMARK.md ---------
    # This reuses `route_for()` above (app/services/verdict.py) -- it is NOT a second "auto"
    # mechanism (§1.2, §5.6). OFF by default: see verdict_enabled_default() docstring. While off,
    # `auto` behaves EXACTLY as before this feature existed (no size estimate is even computed).
    verdict_enabled: bool = field(default_factory=verdict_enabled_default)
    # Candidate-count buckets recorded for audit (`verdict_size_estimate`/`verdict_reason` in
    # metrics_json) alongside the routing decision. docs/SCOPE_BENCHMARK.md measured its
    # small/medium/large cuts on candidate TOKENS, segmented per corpus -- there is no measured cut
    # for a raw candidate COUNT from a single lightweight pre-filter (BaselineIndex.count(), the
    # cheap estimate app/services/verdict.py actually uses), so these are conservative placeholders
    # for LABELING only. They never override MG_ROUTE_*; do not promote them to decide a route
    # without first running scripts/bench_optimizer.py against candidate counts.
    verdict_small_max: int = field(default_factory=lambda: env_int("MG_VERDICT_SMALL_MAX", 15))
    verdict_large_min: int = field(default_factory=lambda: env_int("MG_VERDICT_LARGE_MIN", 50))

    # -- PROVENANCE: one compact line per delivered source (file · type · status · updated · projeto)
    # Never repeats the "treat notes as data" framing the context header already carries, and never
    # adds authority: it states where the text came from, nothing more. OFF by default (orchestrator
    # decision 2026-10-02): the benchmark (arm C_flags_on vs B_flags_off, 520 notes / 120 questions)
    # measured recall 0.9136 -> 0.9136 and fact_in_context 102/110 -> 102/110, i.e. no answer gained,
    # while the provenance lines alone cost ~19.5k tokens (+23.6% context). Token economy (§48) wins
    # until a benefit is measured. Set MG_OPT_PROVENANCE=true to add the lines.
    provenance: bool = field(default_factory=lambda: env_bool("MG_OPT_PROVENANCE", False))

    # -- TEMPORALITY: archived / superseded notes are history, not current truth ------------------
    # Default is DEMOTE, not exclude. The strict reading ("historical notes only when the query asks
    # for history") was measured as arm D_history_strict and it is NOT the default because it loses
    # answers on the same corpus: recall 0.9136 -> 0.7727 and fact_in_context 102/110 -> 87/110
    # (0/120 of those questions even mention history). Demotion keeps the note reachable at the tail
    # with `historical` metadata + the `[histórico]` marker, so a history-seeking query still finds it
    # while current answers win the ranking. Turn the strict rule on per deployment with
    # MG_OPT_HISTORICAL_EXCLUDE=true, and never let it delete anything.
    temporal_demote: bool = field(default_factory=lambda: env_bool("MG_OPT_TEMPORAL_DEMOTE", True))
    historical_demote: float = field(default_factory=lambda: env_float("MG_OPT_HISTORICAL_DEMOTE", 0.5))
    historical_exclude: bool = field(default_factory=lambda: env_bool("MG_OPT_HISTORICAL_EXCLUDE", False))

    # -- CONSISTENCY: two notes answering the same thing with different dates -> newest wins, the
    # older one is demoted and MARKED (never deleted). Overlap is word-5-shingle Jaccard.
    conflict_check: bool = field(default_factory=lambda: env_bool("MG_OPT_CONFLICT_CHECK", True))
    conflict_demote: float = field(default_factory=lambda: env_float("MG_OPT_CONFLICT_DEMOTE", 0.5))
    conflict_overlap: float = field(default_factory=lambda: env_float("MG_OPT_CONFLICT_OVERLAP", 0.6))

    version: str = OPTIMIZER_VERSION

    def route_for(self, complexity: str) -> str:
        target = {
            "SIMPLE": self.route_simple, "MEDIUM": self.route_medium,
            "COMPLEX": self.route_complex, "AMBIGUOUS": self.route_ambiguous,
        }.get(complexity, self.route_ambiguous)
        # An invalid value in .env must never break a request: fall back to the free default.
        return target if target in ROUTE_TARGETS else "baseline"

    @classmethod
    def disabled(cls) -> "OptimizerConfig":
        """Exact pre-layer behaviour. Used by benchmarks as the BEFORE arm."""
        return cls(enabled=False, adaptive_cut=False, near_dedup=False, compact_headers=False,
                   injection_flag=False, result_cache=False, refresh_interval_s=-1.0,
                   verdict_enabled=False, provenance=False, temporal_demote=False,
                   conflict_check=False)

    def with_(self, **kw) -> "OptimizerConfig":
        return replace(self, **kw)
