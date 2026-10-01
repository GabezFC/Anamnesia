"""Retrieval / vault / budgeting configuration."""
from dataclasses import dataclass, field
from pathlib import Path

from config import PROJECT_ROOT, env_bool, env_float, env_int, env_str

# The example corpus that ships WITH the repository. It is the default so that a fresh clone runs
# end to end on any machine, on any OS, with no configuration at all — the project must never
# depend on one developer's home directory.
DEFAULT_VAULT = PROJECT_ROOT / "data" / "synthetic_vault"

# Canonical variable, plus the legacy name kept working for existing .env files.
VAULT_ENV_VAR = "MEMORY_GATEWAY_VAULT"
LEGACY_VAULT_ENV_VAR = "OBSIDIAN_VAULT_PATH"


def resolve_vault_path(raw: str | Path | None = None) -> Path:
    """Resolve the vault directory from an explicit value, the environment, or the bundled corpus.

    Precedence: explicit argument (a CLI `--vault`) > MEMORY_GATEWAY_VAULT > OBSIDIAN_VAULT_PATH >
    the bundled `data/synthetic_vault`. Relative paths resolve against the current working
    directory, absolute paths are used as given, and `~` is expanded, so all of
    `--vault ./data/synthetic_vault`, `--vault ~/notes` and `--vault /srv/vault` behave.
    """
    value = raw or env_str(VAULT_ENV_VAR, "") or env_str(LEGACY_VAULT_ENV_VAR, "")
    if not value:
        return DEFAULT_VAULT
    return Path(str(value)).expanduser().resolve()


def validate_vault_path(path: Path) -> Path:
    """Fail loudly and legibly instead of silently indexing an empty directory."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Vault directory not found: {p}\n"
            f"Set {VAULT_ENV_VAR} in your .env (see .env.example) or pass --vault <path>. "
            f"The repository ships an example corpus at {DEFAULT_VAULT}."
        )
    if not p.is_dir():
        raise NotADirectoryError(f"Vault path is not a directory: {p}")
    return p


def validate_vault_path_for_runtime(path: Path, db_path: str | Path | None = None) -> Path:
    """`validate_vault_path` plus the two extra guards the interactive config page (§3) needs.

    Reuses the exact rules `MemoryGateway.__init__` already enforces (app/gateway/memory_gateway.py:
    benchmark.db must not end up inside the vault) and adds the repo-as-vault case, which the
    gateway never had to check because the bundled example corpus can never equal the repo root.
    A vault switch made through the config page must reject both BEFORE anything is persisted or
    a running gateway is rebuilt against a broken path.
    """
    p = validate_vault_path(path).resolve()
    # Reject the repo root itself, or any ancestor of it (which would make the vault CONTAIN the
    # whole repo -- code, .env, .git). A vault living INSIDE the repo (e.g. the bundled
    # data/synthetic_vault) is fine and is the shipped default, so this must not reject descendants.
    if p == PROJECT_ROOT or p in PROJECT_ROOT.parents:
        raise PermissionError(f"O vault não pode ser o próprio repositório do Memory Gateway (ou um "
                              f"diretório que o contém): {p}")
    if db_path is None:
        from config.benchmark import BenchmarkConfig  # local import: avoids a module-load-order cycle
        db_path = BenchmarkConfig().db_path
    db = Path(db_path).resolve()
    if p in db.parents:
        raise PermissionError(f"benchmark.db ({db}) não pode ficar dentro do vault ({p}) (§58)")
    return p


@dataclass
class RetrievalConfig:
    vault_path: Path = field(default_factory=resolve_vault_path)
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
    # Personalized PageRank graph expansion (§5.5, HippoRAG-style), opt-in. See app/retrieval/ppr.py.
    # Off by default: flag off reproduces the exact BFS behaviour byte-for-byte (tests/test_ppr.py).
    # Never used by graphify_jev (frozen pipeline) regardless of this flag.
    ppr_enabled: bool = field(default_factory=lambda: env_bool("PPR_ENABLED", False))
    ppr_alpha: float = field(default_factory=lambda: env_float("PPR_ALPHA", 0.85))
    ppr_iters: int = field(default_factory=lambda: env_int("PPR_ITERS", 30))
    ppr_top_n: int = field(default_factory=lambda: env_int("PPR_TOP_N", 15))

    @property
    def mirror_dir(self) -> Path:
        return self.data_dir / "vault_mirror"

    @property
    def graph_path(self) -> Path:
        return self.mirror_dir / "graphify-out" / "graph.json"
