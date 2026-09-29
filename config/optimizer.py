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
from dataclasses import dataclass, field, replace

from config import env_bool, env_float, env_int, env_str

# Part of the result-cache key and of every run's metrics. Bump when a stage changes MEANING.
OPTIMIZER_VERSION = "mol-v1"

ROUTE_TARGETS = ("baseline", "graphify", "graphify_jev", "graphify_jev_opt")


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
                   injection_flag=False, result_cache=False, refresh_interval_s=-1.0)

    def with_(self, **kw) -> "OptimizerConfig":
        return replace(self, **kw)
