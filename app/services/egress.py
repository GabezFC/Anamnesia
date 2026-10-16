"""ANAM-004/005: ponto ÚNICO de decisão para saída de rede (egress) do app.

`check_egress(url, purpose)` aplica, nesta ordem:
  1. modo OFFLINE (`app/services/offline.py::ensure_online`): só loopback passa;
  2. esquema: `https` (ou `http` apenas em loopback);
  3. allow-list de hosts: loopback sempre permitido; demais hosts só se estiverem em
     `ANAMNESIA_EGRESS_ALLOW_HOSTS` (lista separada por vírgula; substitui o default quando definida e não vazia).
     Entradas aceitam host exato (`api.openai.com`) ou curinga de subdomínio (`*.exemplo.com`).

Default = apenas os hosts oficiais usados no código (TypeSafe, OpenRouter, OpenAI, Anthropic).

Por que existe: sem isso, `TYPESAFE_BASE_URL` apontando para um host arbitrário exfiltraria snippets do vault
(a chave e o conteúdo viajam para o endpoint). A decisão é logada em `anamnesia.egress` (só esquema/host/propósito
e veredito — nunca caminho, query, headers ou segredos).
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

from app.services.offline import ensure_online, is_loopback_host

log = logging.getLogger("anamnesia.egress")

ALLOW_ENV = "ANAMNESIA_EGRESS_ALLOW_HOSTS"
DEFAULT_ALLOW_HOSTS: tuple[str, ...] = (
    "api.typesafe.ai",     # TYPESAFE_BASE_URL default (jev_setup / TypeSafe SDK)
    "openrouter.ai",       # OpenRouterAdapter
    "api.openai.com",      # OpenAIAdapter
    "api.anthropic.com",   # AnthropicAdapter (SDK)
)


class EgressBlocked(ConnectionError):
    """Destino recusado pela política de egress (esquema ou host fora da allow-list)."""


def allowed_hosts() -> tuple[str, ...]:
    raw = os.environ.get(ALLOW_ENV, "")
    items = tuple(h.strip().lower() for h in raw.split(",") if h.strip())
    return items or DEFAULT_ALLOW_HOSTS


def _host_ok(host: str, allow: tuple[str, ...]) -> bool:
    for a in allow:
        if a.startswith("*."):
            if host.endswith(a[1:]) and len(host) > len(a) - 1:
                return True
        elif host == a:
            return True
    return False


def check_policy(url: str, purpose: str) -> str:
    """Esquema + allow-list (sem checar OFFLINE). Devolve o host; levanta `EgressBlocked`."""
    try:
        parts = urlsplit((url or "").strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        host, parts = "", None
    scheme = parts.scheme.lower() if parts else ""
    if not host or scheme not in ("http", "https"):
        log.warning("egress negado purpose=%s motivo=url_invalida", purpose)
        raise EgressBlocked(f"egress recusado ({purpose}): URL inválida ou esquema não suportado.")
    loop = is_loopback_host(host)
    if scheme == "http" and not loop:
        log.warning("egress negado purpose=%s scheme=http host=%s motivo=esquema", purpose, host)
        raise EgressBlocked(f"egress recusado ({purpose}): esquema http só é permitido em localhost; use https.")
    if not loop and not _host_ok(host, allowed_hosts()):
        log.warning("egress negado purpose=%s host=%s motivo=fora_da_allow_list", purpose, host)
        raise EgressBlocked(
            f"egress recusado ({purpose}): host '{host}' fora da allow-list. "
            f"Adicione-o em {ALLOW_ENV} se for um destino confiável.")
    log.info("egress permitido purpose=%s scheme=%s host=%s", purpose, scheme, host)
    return host


def check_egress(url: str, purpose: str) -> None:
    """Gate único: OFFLINE + esquema + allow-list. Levanta `OfflineBlocked` ou `EgressBlocked`."""
    ensure_online(purpose, url)
    check_policy(url, purpose)
