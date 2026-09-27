"""Retrieval / vault / budgeting configuration."""
from dataclasses import dataclass, field
from pathlib import Path

from config import PROJECT_ROOT, env_bool, env_float, env_int, env_str


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
    # Deterministic pre-filter before the paid judge (0 = disabled, judge every candidate).
    # 8 is deliberately conservative: with hybrid retrieval the ground-truth note arrives at
    # position 0 in 9/10 benchmark questions (worst case position 1), so top-3 already retains
    # 10/10. K=8 keeps ~2.5x that margin for queries unlike the benchmark set while cutting judge
    # input to roughly a third of the old K=25. See app/services/prefilter.py.
    prefilter_top_k: int = field(default_factory=lambda: env_int("PREFILTER_TOP_K", 8))
    prefilter_lexical_weight: float = field(default_factory=lambda: env_float("PREFILTER_LEXICAL_WEIGHT", 0.3))
    # Safety net: if the judge eliminates EVERY candidate, fall back to this many top retrieval
    # candidates instead of returning an empty context. Measured 2026-09-27: the judge scored
    # correct notes 0.07-0.40 on 3 of 10 questions, producing zero survivors and an empty answer
    # while still costing judge tokens. 0 disables the net and restores strict judge-only output.
    jev_min_survivors: int = field(default_factory=lambda: env_int("JEV_MIN_SURVIVORS", 3))
    graphify_bin: str = field(default_factory=lambda: env_str("GRAPHIFY_BIN", "graphify"))
    # Hybrid retrieval: BM25 body text for content + graph edges for structure.
    # The Graphify CLI seeds only from node LABELS (filenames/headings) and never sees body text,
    # so answers living in a note's body were unreachable at any budget. Measured on the 10
    # answerable benchmark questions: hybrid 10/10 recall vs 8/10 for the CLI traversal.
    # Set GRAPHIFY_HYBRID=false to restore the pure-CLI behaviour for comparison.
    graphify_hybrid: bool = field(default_factory=lambda: env_bool("GRAPHIFY_HYBRID", True))
    graphify_text_seeds: int = field(default_factory=lambda: env_int("GRAPHIFY_TEXT_SEEDS", 10))
    graphify_graph_expand: int = field(default_factory=lambda: env_int("GRAPHIFY_GRAPH_EXPAND", 15))
    graphify_query_budget: int = field(default_factory=lambda: env_int("GRAPHIFY_QUERY_BUDGET", 6000))
    graphify_timeout_s: int = field(default_factory=lambda: env_int("GRAPHIFY_TIMEOUT_S", 60))

    @property
    def mirror_dir(self) -> Path:
        return self.data_dir / "vault_mirror"

    @property
    def graph_path(self) -> Path:
        return self.mirror_dir / "graphify-out" / "graph.json"
