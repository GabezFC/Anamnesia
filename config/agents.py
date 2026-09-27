"""Consumer agents / model providers configuration. Availability is always detected at runtime."""
from dataclasses import dataclass, field

from config import env_str


@dataclass
class AgentsConfig:
    ollama_base_url: str = field(default_factory=lambda: env_str("OLLAMA_BASE_URL", "http://localhost:11434"))
    vllm_base_url: str = field(default_factory=lambda: env_str("VLLM_BASE_URL", "http://localhost:8001/v1"))
    openai_compat_base_url: str = field(default_factory=lambda: env_str("OPENAI_COMPAT_BASE_URL", ""))
    openai_compat_model: str = field(default_factory=lambda: env_str("OPENAI_COMPAT_MODEL", ""))
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    hermes_bin: str = field(default_factory=lambda: env_str("HERMES_BIN", "hermes"))
    hermes_provider: str = field(default_factory=lambda: env_str("HERMES_PROVIDER", ""))
    hermes_model: str = field(default_factory=lambda: env_str("HERMES_MODEL", ""))
    claude_bin: str = field(default_factory=lambda: env_str("CLAUDE_BIN", "claude"))
    codex_bin: str = field(default_factory=lambda: env_str("CODEX_BIN", "codex"))
    opencode_bin: str = field(default_factory=lambda: env_str("OPENCODE_BIN", "opencode"))
    generation_temperature: float = 0.0
    generation_max_tokens: int = 800
    agent_timeout_s: int = 600
