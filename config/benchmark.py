"""Benchmark configuration and profiles (§99)."""
from dataclasses import dataclass, field

from config import PROJECT_ROOT, env_bool, env_int, env_str

PROFILES = {
    "benchmark": {"cache_enabled": False, "verbose_metrics": True, "randomize": True, "log_payloads": False},
    "production": {"cache_enabled": True, "verbose_metrics": False, "randomize": False, "log_payloads": False},
    "debug": {"cache_enabled": False, "verbose_metrics": True, "randomize": False, "log_payloads": True},
}

ALLOWED_REPETITIONS = (1, 3, 5, 10)
SWEEP_THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)  # spec §71
# Extra low cutoffs: observed expected sources with JEV relevance 0.18–0.21 (2026-09-24), so the sweep
# must also look below 0.50 to show the recall/context trade-off.
SWEEP_THRESHOLDS_EXTENDED = (0.10, 0.20, 0.30, 0.40) + SWEEP_THRESHOLDS


def _default_questions_path() -> str:
    """Prefer the private local dataset, fall back to the published synthetic example.

    `benchmark/questions.json` is derived from the owner's private vault (real names, business
    decisions, personal note paths), so it is gitignored and never published. The repository ships
    `benchmark/questions.example.json` instead, which has the same schema and question categories
    but fully synthetic content, so a fresh clone still runs. Override with BENCHMARK_QUESTIONS.
    """
    private = PROJECT_ROOT / "benchmark" / "questions.json"
    example = PROJECT_ROOT / "benchmark" / "questions.example.json"
    return str(private if private.exists() else example)


@dataclass
class BenchmarkConfig:
    profile: str = field(default_factory=lambda: env_str("PROFILE", "production"))
    benchmark_mode: bool = field(default_factory=lambda: env_bool("BENCHMARK_MODE", False))
    cache_enabled_env: bool = field(default_factory=lambda: env_bool("CACHE_ENABLED", True))
    questions_path: str = field(default_factory=lambda: env_str("BENCHMARK_QUESTIONS", _default_questions_path()))
    db_path: str = field(default_factory=lambda: env_str("DB_PATH", str(PROJECT_ROOT / "benchmark.db")))
    # Loopback by default (§5.4 da proposta 2026-09-28): a server that starts open on the LAN with
    # no authentication used to be the default. MG_HOST is the canonical override; the legacy HOST
    # var (never documented as network-facing) still works so an existing .env keeps behaving, but
    # no longer defaults to 0.0.0.0 -- opening to the LAN is now an explicit choice.
    host: str = field(default_factory=lambda: env_str("MG_HOST", env_str("HOST", "127.0.0.1")))
    port: int = field(default_factory=lambda: env_int("PORT", 8000))
    seed: int = field(default_factory=lambda: env_int("BENCHMARK_SEED", 42))

    @property
    def cache_enabled(self) -> bool:
        # Benchmark mode always disables every cache (§47).
        if self.benchmark_mode or self.profile == "benchmark":
            return False
        return PROFILES.get(self.profile, PROFILES["production"])["cache_enabled"] and self.cache_enabled_env
