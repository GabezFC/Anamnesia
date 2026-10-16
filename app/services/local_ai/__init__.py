"""IA local gerenciada (ANAM-034/035): runtimes (Colibri, Ollama), provider OpenAI-compativel e download seguro.

Nada aqui instala, baixa ou inicia modelo por conta propria: toda acao mutante e explicita
(``start``/``stop``/``confirm=True``) e todo I/O externo (subprocess, HTTP, disco) e injetavel.
"""
from app.services.local_ai.base import (CmdResult, LocalRuntime, RuntimeError_, RuntimeStatus,  # noqa: F401
                                        parse_json_tolerant)
from app.services.local_ai.colibri import ColibriRuntime  # noqa: F401
from app.services.local_ai.download import DownloadError, download_file, hf_resolve_url, safe_join  # noqa: F401
from app.services.local_ai.ollama import OllamaRuntime  # noqa: F401
from app.services.local_ai.policy import ModelBlocked, ensure_model_allowed  # noqa: F401
from app.services.local_ai.provider import LocalProvider, NotSupported  # noqa: F401
