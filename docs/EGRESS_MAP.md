# Mapa de egress (saída de rede) — ANAM-004 / ANAM-005

Documento escrito à mão (não é gerado).

## Política

Todo código em `app/` que sai da máquina passa por `app/services/egress.py::check_egress(url, purpose)`:

1. **OFFLINE** (`ANAMNESIA_OFFLINE=1` / `OFFLINE=1`, ver `app/services/offline.py`): só loopback passa (`OfflineBlocked`).
2. **Esquema**: `https`; `http` somente em loopback.
3. **Allow-list de hosts**: loopback sempre permitido; demais hosts só se constarem em `ANAMNESIA_EGRESS_ALLOW_HOSTS`
   (vírgula; aceita `*.dominio.com`). Quando definida e não vazia, **substitui** o default. Recusa → `EgressBlocked` (mensagem em PT-BR indicando a variável).
   - Default: `api.typesafe.ai`, `openrouter.ai`, `api.openai.com`, `api.anthropic.com`.
4. Cada decisão é logada em `anamnesia.egress` (propósito, esquema, host, veredito; nunca path/query/headers/segredos).

`jev_setup.validate_base_url` aplica a mesma allow-list ao salvar/testar `TYPESAFE_BASE_URL` (erro `host_not_allowed`,
campo `base_url`), e `TypeSafeBackend.__init__` re-checa em runtime (cobre `.env` editado à mão).

Rede de segurança adicional: `offline.install_if_enabled()` envolve `socket.connect/getaddrinfo` (cobre SDKs). Processos filhos (CLIs de agentes) não são cobertos.

## Pontos de saída em `app/` (todos passam por `check_egress`)

| Módulo | Destino | purpose | Notas |
|---|---|---|---|
| `app/adapters/models/providers.py` `OpenAICompatibleAdapter.generate/list_models` | `base_url` (OpenRouter, OpenAI, Ollama/vLLM) | nome do provider | já tinha `ensure_online`; + allow-list. vLLM remoto exige entrada em `ANAMNESIA_EGRESS_ALLOW_HOSTS` |
| `providers.py` `OllamaAdapter.available` | Ollama (`/api/tags`) | `ollama` | |
| `providers.py` `AnthropicAdapter.generate` | `ANTHROPIC_BASE_URL` ou `api.anthropic.com` (SDK) | `anthropic` | |
| `app/services/jev.py` `TypeSafeBackend.__init__` | `TYPESAFE_BASE_URL` ou `api.typesafe.ai` (SDK `typesafe_sdk`) | `typesafe` | **envia snippets do vault** — ponto crítico da ANAM-004 |
| `app/services/jev_setup.py` `validate_base_url` / `test_connection` | idem | `jev_setup` | validação ao salvar/testar |
| `app/services/jev_ollama.py` `OllamaJevBackend` | Ollama loopback | `jev_ollama` | já era loopback-only |
| `app/retrieval/experiments.py` canal semântico | Ollama loopback (`/api/embed`) | `semantic_embed` | já era loopback-only |
| `app/api/connections.py` `_ollama_probe` | `OLLAMA_HOST` (`/api/tags`) | `ollama_probe` | |
| `app/routing/health.py` `probe_ollama` | Ollama (`/api/tags`) | `health_probe_ollama` | opt-in por flag |
| `app/mcp/bridge.py` `bridge_search` | `MG_MCP_BRIDGE_URL` (REST `/memory/search`) | `mcp-bridge` | leva token Bearer; bridge em LAN precisa constar na allow-list |

## Sem egress real / fora do gate

- `app/main.py::local_ip`: `connect` UDP a `10.255.255.255` só para descobrir a interface local (nenhum pacote é enviado). Sob OFFLINE o wrapper de socket o trata.
- `app/api/workspace.py`, `app/services/hardening.py`, `security.py`: usam apenas `urlsplit` (parsing), sem rede.
- Agentes CLI (`claude`, `codex`): subprocessos; recusados no launcher quando OFFLINE (`ensure_online("agent:<nome>")`).

## Scripts (`scripts/`, fora do gate; ferramentas manuais de operador)

| Script | Destino |
|---|---|
| `e2e_workspace.py` | `127.0.0.1` (servidor local de teste) |
| `measure_onda9.py` | `127.0.0.1:11434` (Ollama) |
| `run_onda4e_openrouter.py` | OpenRouter `/credits` + adaptadores (estes passam pelo gate) |
| `verify_registry.py` | URLs de provedores do registry (`/api/tags`, `/models`), sem header Authorization |

## Como adicionar um novo ponto de saída

Chame `check_egress(url, "<finalidade>")` antes da requisição, adicione o host oficial a `DEFAULT_ALLOW_HOSTS` apenas se for um serviço fixo do produto, e inclua uma linha nesta tabela. Testes: `tests/test_anam004_egress.py`.
