"""Laya (convaiinnovations/laya, Apache-2.0) — decisor local não generativo (ANAM-042).

Todas as variáveis são lidas na construção (default_factory), nunca no import, para que testes e o
painel possam alterar o ambiente. Limiares são EXPERIMENTAIS: escolhidos na metade de calibração do conjunto sintético PT-BR/EN de
docs/bench/anam-042-laya.md (relevância keep=0,25/drop=0,10 para a pergunta de 3 vias; privacidade 0,10 =
recall-first; injeção 0,90). Recalibre com os SEUS dados antes de confiar.
"""
from dataclasses import dataclass, field

from config import env_float, env_int, env_str

LAYA_PACKAGE_PIN = "0.4.8"  # versão do pacote PyPI 'laya' verificada (PyPI 2026-10-15; Apache-2.0)
LAYA_CONFIG_VERSION = "laya-cfg-v1"
LAYA_PROMPT_VERSION = "laya-rel-v2"  # sobe quando o texto das perguntas/critérios mudar (chave de cache/benchmark)
# Revisões HF verificadas via HfApi.model_info em 2026-10-15 (pesos baixados com revision pinada).
LAYA_REVISIONS = {
    "multilingual": ("convaiinnovations/laya-multilingual", "1720e3e3357cfe1e281542e223f8273b0890ca34"),
    "english": ("convaiinnovations/laya", "7b928d828b7b0e022f929d9bd2e44165aa270148"),
}


@dataclass
class LayaConfig:
    # off | inproc | serve | auto   (auto = inproc se 'laya' importável e pesos presentes; senão serve se
    # MG_LAYA_SERVE_URL estiver definida; senão OFF explícito e visível em status()/métricas)
    mode: str = field(default_factory=lambda: env_str("MG_LAYA_MODE", "auto").strip().lower())
    models_dir: str = field(default_factory=lambda: env_str("MG_LAYA_MODELS_DIR", "data/local_ai/models"))
    multilingual_dir: str = field(default_factory=lambda: env_str("MG_LAYA_MULTILINGUAL_DIR", ""))
    english_dir: str = field(default_factory=lambda: env_str("MG_LAYA_ENGLISH_DIR", ""))
    serve_url: str = field(default_factory=lambda: env_str("MG_LAYA_SERVE_URL", ""))  # só loopback; nunca :8000
    timeout_s: float = field(default_factory=lambda: env_float("MG_LAYA_TIMEOUT_S", 20.0))
    # ""=auto por idioma (Router); "multilingual" evita carregar o checkpoint inglês (842 MB) e usa 1 só modelo.
    force_model: str = field(default_factory=lambda: env_str("MG_LAYA_FORCE_MODEL", "").strip().lower())
    device: str = field(default_factory=lambda: env_str("MG_LAYA_DEVICE", "cpu"))
    threads: int = field(default_factory=lambda: env_int("MG_LAYA_THREADS", 0))  # 0 = padrão do torch
    batch_size: int = field(default_factory=lambda: env_int("MG_LAYA_BATCH_SIZE", 16))
    max_state_chars: int = field(default_factory=lambda: env_int("MG_LAYA_MAX_STATE_CHARS", 1500))
    # --- relevância ---
    keep_threshold: float = field(default_factory=lambda: env_float("MG_LAYA_KEEP_THRESHOLD", 0.25))
    drop_threshold: float = field(default_factory=lambda: env_float("MG_LAYA_DROP_THRESHOLD", 0.10))
    # Cascata: abaixo desta `confidence` (campo do Laya; act_probability é inútil) o candidato vai ao JEV.
    min_confidence: float = field(default_factory=lambda: env_float("MG_LAYA_MIN_CONFIDENCE", 0.0))
    temperature: float = field(default_factory=lambda: env_float("MG_LAYA_TEMPERATURE", 1.0))  # refit: bench_laya.py
    calibration_file: str = field(default_factory=lambda: env_str("MG_LAYA_CALIBRATION_FILE", ""))
    # fail_open: sem Laya, candidatos passam SINALIZADOS (laya_fallback=1); fail_closed: nada passa.
    failure_mode: str = field(default_factory=lambda: env_str("MG_LAYA_FAILURE_MODE", "fail_open").strip().lower())
    # --- privacidade / escrita ---
    privacy_threshold: float = field(default_factory=lambda: env_float("MG_LAYA_PRIVACY_THRESHOLD", 0.10))
    # Laya ligado mas indisponível: private=True (fail-closed) ou só regras (rules_only).
    privacy_failure: str = field(default_factory=lambda: env_str("MG_LAYA_PRIVACY_FAILURE", "fail_closed").strip().lower())
    injection_threshold: float = field(default_factory=lambda: env_float("MG_LAYA_INJECTION_THRESHOLD", 0.90))
    # off | warn | block — triagem na ESCRITA de memória (sinal adicional; regras do injection_screen mandam)
    write_triage: str = field(default_factory=lambda: env_str("MG_LAYA_WRITE_TRIAGE", "off").strip().lower())

    def validate(self) -> "LayaConfig":
        if self.mode not in {"off", "inproc", "serve", "auto"}:
            raise ValueError(f"MG_LAYA_MODE inválido: {self.mode!r} (off|inproc|serve|auto)")
        if self.force_model not in {"", "english", "multilingual"}:
            raise ValueError("MG_LAYA_FORCE_MODEL inválido ('', english, multilingual)")
        if self.failure_mode not in {"fail_open", "fail_closed"}:
            raise ValueError("MG_LAYA_FAILURE_MODE inválido (fail_open|fail_closed)")
        if self.privacy_failure not in {"fail_closed", "rules_only"}:
            raise ValueError("MG_LAYA_PRIVACY_FAILURE inválido (fail_closed|rules_only)")
        if self.write_triage not in {"off", "warn", "block"}:
            raise ValueError("MG_LAYA_WRITE_TRIAGE inválido (off|warn|block)")
        if not 0.0 <= self.drop_threshold <= self.keep_threshold <= 1.0:
            raise ValueError("MG_LAYA_DROP_THRESHOLD <= MG_LAYA_KEEP_THRESHOLD, ambos em [0,1]")
        if self.temperature <= 0:
            raise ValueError("MG_LAYA_TEMPERATURE deve ser > 0")
        return self

