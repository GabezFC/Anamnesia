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


@dataclass
class BenchmarkConfig:
    profile: str = field(default_factory=lambda: env_str("PROFILE", "production"))
    benchmark_mode: bool = field(default_factory=lambda: env_bool("BENCHMARK_MODE", False))
    cache_enabled_env: bool = field(default_factory=lambda: env_bool("CACHE_ENABLED", True))
    questions_path: str = field(default_factory=lambda: str(PROJECT_ROOT / "benchmark" / "questions.json"))
    db_path: str = field(default_factory=lambda: env_str("DB_PATH", str(PROJECT_ROOT / "benchmark.db")))
    host: str = field(default_factory=lambda: env_str("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: env_int("PORT", 8000))
    seed: int = field(default_factory=lambda: env_int("BENCHMARK_SEED", 42))

    @property
    def cache_enabled(self) -> bool:
        # Benchmark mode always disables every cache (§47).
        if self.benchmark_mode or self.profile == "benchmark":
            return False
        return PROFILES.get(self.profile, PROFILES["production"])["cache_enabled"] and self.cache_enabled_env
