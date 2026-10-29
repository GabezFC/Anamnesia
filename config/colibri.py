"""Colibri como alternativa de IA local por API (contrato TypeSafe System One, ANAM-041).

Tudo lido na construção (default_factory), nunca no import. O Gateway NUNCA inicia o servidor Colibri:
ele só consome uma URL existente (loopback por padrão; em Docker aponte para o host, ex. host.docker.internal).
Qualidade NÃO medida: nenhum benchmark do Anamnésia rodou com Colibri (Cérebro IA: Anamnesia/Guias-de-usuario-2026-10-24/JEV_LOCAL.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from config import env_bool, env_float, env_int, env_str

COLIBRI_CONFIG_VERSION = "colibri-cfg-v1"

DEFAULT_PORT = 11500          # porta própria do Colibri (nunca 8000 = Gateway, nunca 11434 = Ollama)
FORBIDDEN_PORTS = (8000, 11434)


@dataclass
class ColibriConfig:
    # OFF por padrão: sem servidor Colibri em execução, nada muda no produto.
    enabled: bool = field(default_factory=lambda: env_bool("MG_COLIBRI_ENABLED", False))
    # URL do servidor Colibri já em execução. Em Docker use o host configurável
    # (ex.: http://host.docker.internal:11500) — nunca assuma localhost.
    url: str = field(default_factory=lambda: env_str("MG_COLIBRI_URL", f"http://127.0.0.1:{DEFAULT_PORT}"))
    api_key: str | None = field(default_factory=lambda: env_str("MG_COLIBRI_API_KEY", "") or None)
    model: str = field(default_factory=lambda: env_str("MG_COLIBRI_MODEL", "jev-latest"))
    timeout_s: float = field(default_factory=lambda: env_float("MG_COLIBRI_TIMEOUT_S", 30.0))
    max_retries: int = field(default_factory=lambda: env_int("MG_COLIBRI_MAX_RETRIES", 1))
    # Por padrão só loopback; `allow_docker_host` libera host.docker.internal explicitamente (Docker).
    allow_docker_host: bool = field(default_factory=lambda: env_bool("MG_COLIBRI_ALLOW_DOCKER_HOST", False))
    config_version: str = COLIBRI_CONFIG_VERSION

    def validate(self) -> None:
        if self.max_retries < 0 or self.max_retries > 2:
            raise ValueError("MG_COLIBRI_MAX_RETRIES deve ficar em 0..2 (sem loops de retry)")
        if self.timeout_s <= 0 or self.timeout_s > 120:
            raise ValueError("MG_COLIBRI_TIMEOUT_S deve ficar em (0, 120]")
        if not self.is_loopback_url(self.url, allow_docker_host=self.allow_docker_host):
            raise ValueError(f"MG_COLIBRI_URL deve apontar para loopback (ou host.docker.internal): {self.url}")
        port = urlparse(self.url).port
        if port in FORBIDDEN_PORTS:
            raise ValueError(f"MG_COLIBRI_URL não pode usar a porta reservada {port}")

    @staticmethod
    def is_loopback_url(url: str, *, allow_docker_host: bool = False) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            return False
        if not host:
            return False
        if host in ("127.0.0.1", "localhost", "::1"):
            return True
        return allow_docker_host and host == "host.docker.internal"


def load_colibri_config() -> ColibriConfig:
    cfg = ColibriConfig()
    cfg.validate()
    return cfg
