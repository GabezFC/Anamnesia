"""Retrieval / vault / budgeting configuration."""
from dataclasses import dataclass, field
from pathlib import Path

from config import PROJECT_ROOT, env_int, env_str


@dataclass
class RetrievalConfig:
    vault_path: Path = field(default_factory=lambda: Path(env_str("OBSIDIAN_VAULT_PATH", r"C:\Users\fonse\Cérebro_AI")))
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    # Directories inside the vault that are never indexed.
    excluded_dirs: tuple[str, ...] = (".obsidian", ".trash", ".git", "99-Templates")
    max_candidates: int = field(default_factory=lambda: env_int("MAX_CANDIDATES", 100))
    snippet_max_tokens: int = field(default_factory=lambda: env_int("SNIPPET_MAX_TOKENS", 300))
    dedup_max_per_note: int = field(default_factory=lambda: env_int("DEDUP_MAX_PER_NOTE", 1))
    # Budget of the final context delivered to ANY consumer model (§29 CLAUDE_CONTEXT_BUDGET, renamed neutral).
    model_context_budget: int = field(default_factory=lambda: env_int("MODEL_CONTEXT_BUDGET", env_int("CLAUDE_CONTEXT_BUDGET", 6000)))
    per_source_max_tokens: int = field(default_factory=lambda: env_int("PER_SOURCE_MAX_TOKENS", 1500))
    graphify_bin: str = field(default_factory=lambda: env_str("GRAPHIFY_BIN", "graphify"))
    graphify_query_budget: int = field(default_factory=lambda: env_int("GRAPHIFY_QUERY_BUDGET", 6000))
    graphify_timeout_s: int = field(default_factory=lambda: env_int("GRAPHIFY_TIMEOUT_S", 60))

    @property
    def mirror_dir(self) -> Path:
        return self.data_dir / "vault_mirror"

    @property
    def graph_path(self) -> Path:
        return self.mirror_dir / "graphify-out" / "graph.json"
