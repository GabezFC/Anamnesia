"""JEV (TypeSafe System One) configuration. All thresholds are experimental, not definitive (§23)."""
from dataclasses import dataclass, field

from config import env_bool, env_float, env_int, env_str

# Bump whenever question wording/criteria change: part of the cache key and benchmark identity (§45).
# v2 (2026-09-27): candidate payload slimmed — dropped the redundant `id` (repeated `source`) and
# send the note basename plus a short int `ref` instead of the full vault path. Wording unchanged.
JEV_PROMPT_VERSION = "relevance-v2+injection-v1"
JEV_CONFIG_VERSION = "cfg-v1"


@dataclass
class JevConfig:
    model: str = field(default_factory=lambda: env_str("JEV_MODEL", "jev-1.13.0"))
    mode: str = field(default_factory=lambda: env_str("JEV_MODE", "performance"))  # performance | strict
    # Operational budget per request (docs: 64k total per request).
    context_budget: int = field(default_factory=lambda: env_int("JEV_CONTEXT_BUDGET", 48000))
    # Docs: 32k tokens for `state` plus the longest question. Keep a safety margin.
    state_budget: int = field(default_factory=lambda: env_int("JEV_STATE_BUDGET", 28000))
    relevance_threshold: float = field(default_factory=lambda: env_float("JEV_RELEVANCE_THRESHOLD", 0.78))
    review_threshold: float = field(default_factory=lambda: env_float("JEV_REVIEW_THRESHOLD", 0.55))
    injection_threshold: float = field(default_factory=lambda: env_float("JEV_INJECTION_THRESHOLD", 0.80))
    review_action: str = field(default_factory=lambda: env_str("JEV_REVIEW_ACTION", "keep"))  # keep | drop
    second_pass: bool = field(default_factory=lambda: env_bool("JEV_SECOND_PASS", False))
    contradiction_check: bool = field(default_factory=lambda: env_bool("JEV_CONTRADICTION_CHECK", False))
    failure_mode: str = field(default_factory=lambda: env_str("JEV_FAILURE_MODE", "fail_open"))  # fail_open | fail_closed
    max_concurrent_requests: int = field(default_factory=lambda: env_int("JEV_MAX_CONCURRENT_REQUESTS", 2))
    max_retries: int = field(default_factory=lambda: env_int("JEV_MAX_RETRIES", 2))
    timeout_s: float = field(default_factory=lambda: env_float("JEV_TIMEOUT_S", 30.0))
    prompt_version: str = JEV_PROMPT_VERSION
    config_version: str = JEV_CONFIG_VERSION

    def validate(self) -> None:
        if self.mode not in {"performance", "strict"}:
            raise ValueError(f"JEV_MODE inválido: {self.mode}")
        if self.review_action not in {"keep", "drop"}:
            raise ValueError(f"JEV_REVIEW_ACTION inválido: {self.review_action}")
        if self.failure_mode not in {"fail_open", "fail_closed"}:
            raise ValueError(f"JEV_FAILURE_MODE inválido: {self.failure_mode}")
        if not (0 <= self.review_threshold <= self.relevance_threshold <= 1):
            raise ValueError("Requer 0 <= REVIEW_THRESHOLD <= RELEVANCE_THRESHOLD <= 1")
