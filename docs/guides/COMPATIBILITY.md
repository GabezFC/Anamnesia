# Matriz de compatibilidade testada (ANA-218)

Cada linha liga uma combinação a **um teste automatizado** que existe no repositório
(`tests/test_onda8_integrations.py` valida que o arquivo e a função citados existem). "Testado" significa
*coberto por teste hermético com dublê* (servidor falso em loopback ou CLI simulada na fronteira `_run`),
**não** que a combinação foi exercitada contra o serviço real. O que não tem teste está na seção final.

| Componente | Combinação | Garantia | Status | Teste |
| --- | --- | --- | --- | --- |
| Provedor de modelo | OpenAI-compatível (Ollama/vLLM/gateways) via `POST /chat/completions` | resposta, tokens, `list_models`, cabeçalho Bearer | testado (servidor falso) | `tests/test_onda8_integrations.py::test_openai_compatible_against_fake_server` |
| Provedor de modelo | OpenAI-compatível: 401 e 429 | taxonomia `auth` / `rate_limit` + `Retry-After` | testado (servidor falso) | `tests/test_onda8_integrations.py::test_openai_compatible_error_taxonomy_against_fake_server` |
| Consumidor genérico | `GenericConsumer("openai_compatible")` | roteia ao adaptador e devolve `GenerationResult` | testado (servidor falso) | `tests/test_onda8_integrations.py::test_generic_consumer_openai_compatible_against_fake_server` |
| Agente | Claude Code CLI 2.1 (`claude -p --output-format json`) | `available()`, tokens (incl. cache), custo, flags de isolamento | testado (CLI simulada) | `tests/test_onda8_integrations.py::test_claude_code_adapter_available_and_generate` |
| Agente | Codex CLI 0.155 (`codex exec --json -o`) | login, tokens do evento `turn.completed`, arquivo temporário removido | testado (CLI simulada) | `tests/test_onda8_integrations.py::test_codex_adapter_available_and_generate` |
| Agente | OpenCode 1.18 | apenas detecção; `generate` recusa (adaptador não validado) | testado (CLI simulada) | `tests/test_onda8_integrations.py::test_opencode_adapter_is_prepared_not_validated` |
| Agente real | Claude Code / Codex logados | contrato de `available()`/`generate()` | opt-in (`ANAMNESIA_REAL_AGENT`), pulado por padrão | `tests/test_onda8_integrations.py::test_real_agent_contract` |
| MCP | servidor stdio (`memory_search` + toolset `full`) | anotações de ferramenta e `outputSchema` | testado (subprocesso) | `tests/test_onda8_integrations.py::test_mcp_tools_have_annotations_and_output_schema` |
| MCP | resources/prompts | só aparecem com `MG_MCP_RESOURCES=1` | testado (subprocesso) | `tests/test_onda8_integrations.py::test_mcp_resources_prompts_are_opt_in` |
| MCP → REST | `MG_MCP_BRIDGE_URL` + `Authorization: Bearer` opcional | token só enviado se configurado; nunca vaza em erro | testado (REST falso) | `tests/test_onda8_integrations.py::test_bridge_sends_bearer_only_when_configured` |
| Snippets MCP | Hermes (YAML), Claude Code (JSON), Codex (TOML) | conteúdo parseável no formato de destino | testado | `tests/test_onda8_integrations.py::test_snippets_are_valid_in_their_formats` |
| Docker | `Dockerfile` + `docker-compose.yml` | base fixada por digest, usuário não-root, porta só em loopback | testado (estático, sem `docker build`) | `tests/test_onda8_integrations.py::test_dockerfile_base_image_pinned_by_digest_and_non_root` |
| CI | job `e2e-browser` separado | existe, isolado do job de unidade | testado (estático) | `tests/test_onda8_integrations.py::test_ci_has_separate_browser_e2e_job` |
| Modo offline | `OFFLINE=1` | nenhuma conexão não-loopback é aberta | testado (guarda de socket) | `tests/test_onda8_integrations.py::test_offline_blocks_external_connect_without_opening_it` |

## Não testado (não afirme suporte)

- Anthropic, OpenAI e OpenRouter **reais**: só o caminho de erro/bloqueio é testado; nenhuma chamada paga é feita pela suíte.
- vLLM real: o adaptador é o mesmo OpenAI-compatível e foi testado só contra o servidor falso.
- OpenCode: `generate` é deliberadamente inoperante até existir credencial para validar.
- Hermes: coberto por outros testes de integração, não por esta matriz.
- Docker: **nenhum `docker build`/`compose up` foi executado** nesta onda; o digest foi lido da API do registro,
  não de uma imagem construída. O build/health-check documentado em `QUICKSTART.md` vem de verificação anterior.
- Job `e2e-browser` do CI: validado com `actionlint`, **ainda não executado** em um runner real.
- Linux/macOS para PTY e Windows para o servidor MCP em `OFFLINE=1`: sem teste dedicado nesta matriz.
