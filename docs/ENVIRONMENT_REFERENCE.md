<!-- GERADO por scripts/gen_config_reference.py (ANA-073). NÃO edite à mão: rode o script. -->
<!-- tests/test_docs_env.py falha se esta tabela divergir do código. -->

# Referência de variáveis de ambiente (gerada)

200 variáveis lidas pelo código (`app/`, `config/`, `anamnesia/`, `memory_gateway/`).
Hierarquia de precedência: [CONFIGURATION.md](guides/CONFIGURATION.md). Modelo comentado para copiar: [`.env.example`](../.env.example).

**Tipo**: `user` = você define; `interna` = escrita/derivada pelo próprio Gateway; `sistema` = do SO/git.

## ANAMNESIA_*

| Variável | Tipo | Default no código | Descrição | Lida em |
| --- | --- | --- | --- | --- |
| `ANAMNESIA_ALLOW_NETWORK_TEST` | user | — | [user] Permite o botão "testar conexão" fazer chamadas de rede reais (1). Padrão: teste estrutural offline. | `app/api/connections.py` |
| `ANAMNESIA_ALLOW_REMOTE_TERMINALS` | user | `''` | — | `app/api/workspace.py` |
| `ANAMNESIA_ANSWER_REQUIRE_JEV_STRICT` | user | `''` | [user] mode=answer exige JEV strict na recuperação (1). | `app/routing/answer.py` |
| `ANAMNESIA_BUDGET_ENFORCE` | user | `''` | — | `app/gateway/budget_guard.py` |
| `ANAMNESIA_CONTEXT_TTL_DAYS` | user | `'0'` | [user] Purga no start o texto de contexto dos runs mais velhos que N dias (0 = desligado). | `app/main.py` |
| `ANAMNESIA_DELEGATE` | user | `''` | [user] mode=delegate: liga (1), launcher, preset e perfil do orquestrador. | `app/orchestration/delegate.py` |
| `ANAMNESIA_DELEGATE_LAUNCHER` | user | `''` | — | `app/orchestration/delegate.py` |
| `ANAMNESIA_DELEGATE_PRESET` | user | `''` | — | `app/orchestration/delegate.py` |
| `ANAMNESIA_DELEGATE_PROFILE` | user | `''` | — | `app/orchestration/delegate.py` |
| `ANAMNESIA_EXEC_ALLOWLIST` | user | `''` | — | `app/services/exec_guard.py` |
| `ANAMNESIA_EXEC_GUARD` | user | — | — | `app/services/exec_guard.py` |
| `ANAMNESIA_HOME` | user | `''` | [user] Raiz dos dados (.env, benchmark.db, logs/, data/, local_settings.json). Vence qualquer outro critério. | `config/paths.py` |
| `ANAMNESIA_MAX_SESSIONS` | user | — | [user] Máximo de sessões PTY simultâneas (default 8). | `app/terminals/manager.py` |
| `ANAMNESIA_METRICS_ONLY` | user | `''` | [user] Grava só hash + fontes, nunca o texto do contexto entregue (1 liga). MG_METRICS_ONLY faz o mesmo nas rotas de custo/contexto. | `app/database/db.py` |
| `ANAMNESIA_MODEL_ID` | interna | — | id do modelo do passo, exportado pelo orquestrador | `app/orchestration/launchers.py` |
| `ANAMNESIA_PROJECT_GUARD` | user | `'enforce'` | [user] Guarda de projetos e de execução: enforce (padrão) \| warn \| off. Allowlist extra de executáveis (vírgula). | `app/services/project_guard.py` |
| `ANAMNESIA_ROLE` | interna | — | papel do passo, exportado pelo orquestrador ao subagente | `app/orchestration/launchers.py` |
| `ANAMNESIA_ROUTING` | user | `''` | [user] Liga o router de modelos (1) e escolhe o preset (balanced padrão). | `app/routing/answer.py` |
| `ANAMNESIA_ROUTING_PRESET` | user | `'balanced'` | — | `app/routing/answer.py` |
| `ANAMNESIA_RUN_CONTEXT_BUDGET` | user | — | — | `app/services/context_plan.py` |
| `ANAMNESIA_SAVE_GATE` | user | `'enforce'` | [user] Gate do memory_save quando MG_SCOPE fixa o projeto: enforce (padrão) \| off. | `app/mcp/server.py` |
| `ANAMNESIA_STEP` | interna | — | id do passo, exportado pelo orquestrador | `app/orchestration/launchers.py` |
| `ANAMNESIA_STEP_DIR` | interna | — | diretório do passo, exportado pelo orquestrador | `app/orchestration/launchers.py` |
| `ANAMNESIA_TOKEN_CALIBRATION` | user | `''` | — | `app/services/token_estimate.py` |

## JEV / TypeSafe

| Variável | Tipo | Default no código | Descrição | Lida em |
| --- | --- | --- | --- | --- |
| `JEV_CONTEXT_BUDGET` | user | `48000` | Max tokens of retrieved context sent to the judge per request. | `config/jev.py` |
| `JEV_CONTRADICTION_CHECK` | user | `False` | Ask the judge to check candidates for mutual contradictions. | `config/jev.py` |
| `JEV_FAILURE_MODE` | user | `'fail_open'` | Behaviour when the judge is unreachable: fail_open \| fail_closed. | `config/jev.py` |
| `JEV_INJECTION_THRESHOLD` | user | `0.8` | Injection probability above which a candidate is quarantined. | `config/jev.py` |
| `JEV_MAX_CONCURRENT_REQUESTS` | user | `2` | Max concurrent in-flight requests to the JEV API. | `config/jev.py` |
| `JEV_MAX_RETRIES` | user | `2` | Retries per JEV request before giving up. | `config/jev.py` |
| `JEV_MIN_SURVIVORS` | user | `3` | Safety net: if the judge eliminates every candidate, return this many top retrieval | `config/retrieval.py` |
| `JEV_MODE` | user | `'performance'` | Judge mode profile (e.g. performance \| economy). | `config/jev.py` |
| `JEV_MODEL` | user | `'jev-1.13.0'` | Pinned JEV model ID used for judging candidates. | `config/jev.py` |
| `JEV_RELEVANCE_THRESHOLD` | user | `0.78` | Minimum relevance probability for a candidate to be kept. | `config/jev.py` |
| `JEV_REVIEW_ACTION` | user | `'keep'` | What to do with review-flagged candidates: keep \| drop. | `config/jev.py` |
| `JEV_REVIEW_THRESHOLD` | user | `0.55` | Relevance probability below which a candidate is flagged for review. | `config/jev.py` |
| `JEV_SECOND_PASS` | user | `False` | Run a second judging pass over surviving candidates. | `config/jev.py` |
| `JEV_STATE_BUDGET` | user | `28000` | Max tokens allotted to the JEV `state` payload. | `config/jev.py` |
| `JEV_TIMEOUT_S` | user | `30.0` | Per-request JEV HTTP timeout, in seconds. | `config/jev.py` |
| `TYPESAFE_API_KEY` | user | `''` | Secret: TypeSafe API key. Leave empty here; set it only in your local .env. | `anamnesia/cli.py`, `app/api/routes.py`, `app/gateway/budget_guard.py` |

## MG_*

| Variável | Tipo | Default no código | Descrição | Lida em |
| --- | --- | --- | --- | --- |
| `MG_ALLOWED_HOSTS` | user | `''` | [user] Hosts extras aceitos no cabeçalho Host (proteção contra DNS rebinding), separados por vírgula. | `app/main.py` |
| `MG_ALLOW_REMOTE_PROVIDERS` | user | `''` | — | `app/services/hardening.py` |
| `MG_CONTEXT_NONCE` | user | `'0'` | [user] Nonce por contexto (delimitadores não adivinháveis) nos pipelines não congelados (1 liga). | `app/gateway/memory_gateway.py` |
| `MG_HOST` | user | `'0.0.0.0'` | Interface the API server binds to. Loopback by default (§5.4 da proposta 2026-09-28): endpoints | `app/api/workspace.py`, `config/benchmark.py` |
| `MG_INCREMENTAL_INDEX` | user | `''` | — | `app/retrieval/incremental_index.py` |
| `MG_LOCAL_TOKEN` | interna | — | gerada no primeiro start e gravada no .env; não defina à mão | `anamnesia/cli.py`, `app/services/security.py` |
| `MG_LOG_REDACT` | user | `'1'` | [user] Filtros de redação no log de acesso e caminhos nos logs (1 = ligado; 0/off desliga). | `app/services/hardening.py` |
| `MG_MAX_BODY_BYTES` | user | — | [user] Limite do corpo de requisição / de uploads, em bytes (default no código: 262144 e 1048576). | `app/services/request_guards.py` |
| `MG_MAX_UPLOAD_BYTES` | user | — | — | `app/services/request_guards.py` |
| `MG_MCP_RESPONSE` | user | `'compact'` | MCP: compact = context + run_id + cost metrics; full = adds sources and all metrics. | `app/mcp/server.py` |
| `MG_MCP_SAVE` | user | `'0'` | [user] Liga a tool MCP memory_save (1). Desligada por padrão. | `app/mcp/server.py` |
| `MG_MCP_TOOLSET` | user | `'minimal'` | MCP: minimal = one tool (memory_search); full = the 7 legacy tools. | `app/mcp/server.py`, `app/terminals/mcp_inject.py` |
| `MG_MEMORY_DEDUPE` | user | `'warn'` | — | `app/memory_store/lifecycle.py` |
| `MG_MEMORY_EXPIRED_EXCLUDE` | user | `'1'` | — | `app/services/provenance.py` |
| `MG_MEMORY_FORGET_BACKUP` | user | `True` | — | `app/memory_store/store.py` |
| `MG_MEMORY_SCHEMA_V2` | user | `True` | [user] Chaves de rollback (1 = comportamento novo, padrão): esquema v2, lixeira ao apagar, backup no forget_all. | `app/memory_store/store.py` |
| `MG_MEMORY_SOFT_DELETE` | user | `True` | — | `app/memory_store/store.py` |
| `MG_MEMORY_TRASH_DAYS` | user | `30.0` | — | `app/memory_store/lifecycle.py` |
| `MG_METRICS_ONLY` | user | `''` | — | `app/api/costs.py`, `app/api/memory_context.py` |
| `MG_OPTIMIZER` | user | `True` | Full reference: docs/OPTIMIZATION_LAYER.md. false = exact pre-layer behaviour. | `config/optimizer.py` |
| `MG_OPT_ADAPTIVE_CUT` | user | `True` | Drop results scoring < RATIO x best (SIMPLE/MEDIUM only), never fewer than FLOOR. Calibrated knee. | `config/optimizer.py` |
| `MG_OPT_CACHE_SIZE` | user | `256` | — | `config/optimizer.py` |
| `MG_OPT_CACHE_TTL_S` | user | `900.0` | — | `config/optimizer.py` |
| `MG_OPT_COMPACT_HEADERS` | user | `True` | Omit the redundant section attribute on <note> blocks. | `config/optimizer.py` |
| `MG_OPT_CONFLICT_CHECK` | user | `True` | — | `config/optimizer.py` |
| `MG_OPT_CONFLICT_DEMOTE` | user | `0.5` | — | `config/optimizer.py` |
| `MG_OPT_CONFLICT_OVERLAP` | user | `0.6` | — | `config/optimizer.py` |
| `MG_OPT_CUT_FLOOR` | user | `3` | — | `config/optimizer.py` |
| `MG_OPT_CUT_RATIO` | user | `0.5` | — | `config/optimizer.py` |
| `MG_OPT_HEADER_SECTION_CHARS` | user | `60` | — | `config/optimizer.py` |
| `MG_OPT_HISTORICAL_DEMOTE` | user | `0.5` | — | `config/optimizer.py` |
| `MG_OPT_HISTORICAL_EXCLUDE` | user | `False` | — | `config/optimizer.py` |
| `MG_OPT_INJECTION_FLAG` | user | `True` | Mark (never alter) notes with strong instruction-override phrases. | `config/optimizer.py` |
| `MG_OPT_NEAR_DEDUP` | user | `True` | Collapse near-duplicate notes in the final context. | `config/optimizer.py` |
| `MG_OPT_NEAR_DEDUP_THRESHOLD` | user | `0.88` | — | `config/optimizer.py` |
| `MG_OPT_PROVENANCE` | user | `False` | — | `config/optimizer.py` |
| `MG_OPT_PROVENANCE_MODE` | user | `'full'` | — | `config/optimizer.py` |
| `MG_OPT_RESULT_CACHE` | user | `True` | In-process result cache (production profile only). | `config/optimizer.py` |
| `MG_OPT_TEMPORAL_DEMOTE` | user | `True` | — | `config/optimizer.py` |
| `MG_PROJECT_PATH` | user | — | — | `app/orchestration/delegate.py` |
| `MG_PROJECT_ROOTS` | user | `''` | [user] Raízes onde projetos podem ser registrados (separadas por os.pathsep ou vírgula). | `app/services/project_guard.py` |
| `MG_PROVIDER_URL_GUARD` | user | `'enforce'` | [user] Guarda de URL dos providers: enforce (padrão) \| warn \| off. Hosts não-loopback exigem a flag abaixo. | `app/services/hardening.py` |
| `MG_PTY_AGENT_IDLE_SECONDS` | user | `''` | — | `app/services/hardening.py` |
| `MG_PTY_LIMITS` | user | `'on'` | [user] Limites do Job Object dos PTYs: on (padrão) \| off. Ociosidade de agentes sem cliente, em segundos. | `app/services/hardening.py` |
| `MG_PTY_NO_HOME` | user | `''` | [user] 1 = não repassa HOME/USERPROFILE ao PTY. | `app/terminals/manager.py` |
| `MG_RATE_LIMIT_PER_MIN` | user | — | [user] Requisições por minuto nas rotas de busca/geração/benchmark (0 = sem limite; default 600). | `app/services/request_guards.py` |
| `MG_REDACT_PATHS` | user | `'lan'` | [user] Redação de caminhos absolutos nas respostas: lan (padrão, só clientes não-loopback) \| always \| never. | `app/services/hardening.py` |
| `MG_ROUTE_AMBIGUOUS` | user | `'baseline'` | — | `config/optimizer.py` |
| `MG_ROUTE_COMPLEX` | user | `'baseline'` | — | `config/optimizer.py` |
| `MG_ROUTE_MEDIUM` | user | `'baseline'` | — | `config/optimizer.py` |
| `MG_ROUTE_SIMPLE` | user | `'baseline'` | Pipeline chosen by pipeline="auto" per query class (baseline\|graphify\|graphify_jev\|graphify_jev_opt). | `config/optimizer.py` |
| `MG_SAVED_MAX_BYTES` | user | — | [user] Limites: bytes por nota (default 65536) e notas por minuto (default 30). | `app/memory_store/store.py` |
| `MG_SAVED_RATE_PER_MIN` | user | — | — | `app/memory_store/store.py` |
| `MG_SCOPE` | user | `''` | [user] Fixa o escopo do MCP / caminho do projeto do agente (normalmente injetados pelo Gateway). | `app/mcp/server.py` |
| `MG_SECRETS_BACKEND` | user | `''` | [user] Backend dos segredos de modelos: vazio = .env (padrão) \| keyring. | `app/connections/secrets.py` |
| `MG_TERMINAL_MCP` | user | `'1'` | [user] Injeta o MCP do Gateway nos agentes dos terminais (1 = sim, padrão). | `app/terminals/mcp_inject.py` |
| `MG_TERMINAL_SESSION` | interna | — | id da sessão de terminal, exportado pelo Gateway ao PTY | `app/database/db.py` |
| `MG_VAULT_REFRESH_S` | user | `5.0` | Seconds between vault change checks; the index rebuilds when notes change. -1 = never. | `config/optimizer.py` |
| `MG_VERDICT_ENABLED` | user | `False` | [user] Veredito por escopo (desligado): liga e limiares de tamanho de escopo. | `config/optimizer.py` |
| `MG_VERDICT_LARGE_MIN` | user | `50` | — | `config/optimizer.py` |
| `MG_VERDICT_SMALL_MAX` | user | `15` | — | `config/optimizer.py` |

## Outras

| Variável | Tipo | Default no código | Descrição | Lida em |
| --- | --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | user | — | Secret: Anthropic API key. Leave empty unless using the Anthropic consumer. | `app/adapters/agents/agents.py`, `app/adapters/registry.py` |
| `BENCHMARK_MODE` | user | `False` | Enable benchmark instrumentation and deterministic behaviour. | `config/benchmark.py` |
| `BENCHMARK_QUESTIONS` | user | — | — | `config/benchmark.py` |
| `BENCHMARK_SEED` | user | `42` | RNG seed used when BENCHMARK_MODE is on. | `config/benchmark.py` |
| `CACHE_ENABLED` | user | `True` | Enable the retrieval/judge result cache. | `config/benchmark.py` |
| `CLAUDE_BIN` | user | `'claude'` | [user] Binários dos agentes (nome no PATH ou caminho). | `config/agents.py` |
| `CLAUDE_CONTEXT_BUDGET` | user | `6000` | [user] Orçamento de contexto do consumidor Claude e timeout do Graphify (s). | `config/retrieval.py` |
| `CODEX_BIN` | user | `'codex'` | — | `config/agents.py` |
| `DB_COMPRESS_CONTEXT` | user | `False` | [user] Comprime runs.context com zlib ao gravar (ferramentas que leem o SQLite direto veriam base64). | `config/benchmark.py` |
| `DB_PATH` | user | — | [user] Caminho do SQLite de métricas e do arquivo de perguntas do benchmark (default: <raiz dos dados>). | `config/benchmark.py` |
| `DEDUP_MAX_PER_NOTE` | user | `1` | Max snippets kept per source note after dedup. | `config/retrieval.py` |
| `GIT_OPTIONAL_LOCKS` | sistema | — | definida pelo Gateway ao chamar git | `app/terminals/worktrees.py` |
| `GIT_TERMINAL_PROMPT` | sistema | — | definida pelo Gateway ao chamar git | `app/terminals/worktrees.py` |
| `GRAPHIFY_BIN` | user | `'graphify'` | Graphify executable name or path (must be on PATH if unqualified). | `config/retrieval.py` |
| `GRAPHIFY_GRAPH_EXPAND` | user | `15` | Number of extra nodes reached by expanding graph edges from the seeds. | `config/retrieval.py` |
| `GRAPHIFY_HYBRID` | user | `True` | Hybrid Graphify retrieval: BM25 body text + graph edges. false = old CLI traversal. | `config/retrieval.py` |
| `GRAPHIFY_QUERY_BUDGET` | user | `6000` | Token budget passed to `graphify query --budget`. | `config/retrieval.py` |
| `GRAPHIFY_STALE_FALLBACK_S` | user | `0.0` | — | `config/retrieval.py` |
| `GRAPHIFY_TEXT_SEEDS` | user | `10` | Number of BM25 text hits used as graph traversal seeds. | `config/retrieval.py` |
| `GRAPHIFY_TIMEOUT_S` | user | `60` | — | `config/retrieval.py` |
| `HERMES_BIN` | user | `'hermes'` | — | `config/agents.py` |
| `HERMES_MODEL` | user | `''` | Model name passed to the Hermes consumer adapter. | `config/agents.py` |
| `HERMES_PROVIDER` | user | `''` | Provider name passed to the Hermes consumer adapter. | `config/agents.py` |
| `HOST` | user | `'127.0.0.1'` | [user] Alias legado de MG_HOST (só é lido se MG_HOST estiver vazio). Prefira MG_HOST. | `config/benchmark.py` |
| `LOCALAPPDATA` | sistema | — | diretório de dados do Windows (base do diretório do usuário) | `config/paths.py` |
| `MAX_CANDIDATES` | user | `100` | Max candidate notes pulled from retrieval before filtering. | `config/retrieval.py` |
| `MEMORY_GATEWAY_URL` | interna | — | URL do Gateway injetada pelo Gateway no MCP/PTY do agente | `app/terminals/mcp_inject.py` |
| `MEMORY_GATEWAY_VAULT` | user | `''` | Absolute or relative path to the Obsidian-style vault the Gateway reads notes from. | `app/api/routes.py`, `config/retrieval.py` |
| `MODEL_CONTEXT_BUDGET` | user | — | Total token budget of the context handed to the consumer model. | `config/retrieval.py` |
| `OBSIDIAN_VAULT_PATH` | user | `''` | Linux/macOS example:   MEMORY_GATEWAY_VAULT=/home/user/notes | `config/retrieval.py` |
| `OLLAMA_BASE_URL` | user | `'http://localhost:11434'` | Base URL of a local Ollama server. | `config/agents.py` |
| `OLLAMA_HOST` | user | — | [user] Alias do endpoint do Ollama usado pelo teste de conexão (a config principal é OLLAMA_BASE_URL). | `app/api/connections.py` |
| `OPENAI_API_KEY` | user | — | Secret: OpenAI API key. Leave empty unless using the OpenAI consumer. | `app/adapters/models/providers.py`, `app/adapters/registry.py` |
| `OPENAI_COMPAT_API_KEY` | user | — | Secret: API key for that OpenAI-compatible endpoint, if it requires one. | `app/adapters/registry.py` |
| `OPENAI_COMPAT_BASE_URL` | user | `''` | Base URL of any other OpenAI-compatible endpoint. | `config/agents.py` |
| `OPENAI_COMPAT_MODEL` | user | `''` | Model name to request from that OpenAI-compatible endpoint. | `config/agents.py` |
| `OPENCODE_BIN` | user | `'opencode'` | — | `config/agents.py` |
| `OPENROUTER_API_KEY` | user | — | Secret: OpenRouter API key. Leave empty unless using the OpenRouter consumer. | `app/adapters/models/providers.py`, `app/adapters/registry.py` |
| `OPT_ADAPTIVE_K` | user | `False` | — | `config/optimization.py` |
| `OPT_ADAPTIVE_K_MAX` | user | `20` | — | `config/optimization.py` |
| `OPT_CACHE_L2` | user | `True` | — | `config/optimization.py` |
| `OPT_CACHE_L3_SHADOW` | user | `True` | — | `config/optimization.py` |
| `OPT_CACHE_PROMOTE_L3` | user | `False` | — | `config/optimization.py` |
| `OPT_CACHE_RANKING` | user | `False` | — | `config/optimization.py` |
| `OPT_CACHE_SNIPPETS` | user | `False` | — | `config/optimization.py` |
| `OPT_EARLY_STOPPING` | user | `False` | — | `config/optimization.py` |
| `OPT_EARLY_STOP_MAX_ACCEPT_RANK` | user | `3` | — | `config/optimization.py` |
| `OPT_EARLY_STOP_MIN_STRONG` | user | `1` | — | `config/optimization.py` |
| `OPT_ENABLED` | user | `False` | e docs/reports/OPTIONAL_STAGES_BENCHMARK.md). Estágios com modelo exigem extras opcionais. --- | `config/optimization.py` |
| `OPT_LAYERED_CACHE` | user | `False` | — | `config/optimization.py` |
| `OPT_NEAR_DEDUP` | user | `False` | — | `config/optimization.py` |
| `OPT_NEAR_DEDUP_HAMMING` | user | `12` | — | `config/optimization.py` |
| `OPT_NEAR_DEDUP_THRESHOLD` | user | `0.88` | — | `config/optimization.py` |
| `OPT_PROGRESSIVE_BAND` | user | `0.12` | — | `config/optimization.py` |
| `OPT_PROGRESSIVE_CONTEXT` | user | `False` | — | `config/optimization.py` |
| `OPT_PROGRESSIVE_FIRST_TOKENS` | user | `300` | — | `config/optimization.py` |
| `OPT_PROGRESSIVE_SECOND_TOKENS` | user | `600` | — | `config/optimization.py` |
| `OPT_QUERY_PROFILING` | user | `True` | — | `config/optimization.py` |
| `OPT_RECORD_SHADOW` | user | `True` | — | `config/optimization.py` |
| `OPT_SMART_SNIPPET` | user | `False` | — | `config/optimization.py` |
| `OPT_SNIPPET_FOR_FROZEN` | user | `False` | — | `config/optimization.py` |
| `OPT_SNIPPET_MIN_SAVING` | user | `40` | — | `config/optimization.py` |
| `OPT_SNIPPET_TOKENS` | user | `300` | — | `config/optimization.py` |
| `OPT_STAGES_PRESET` | user | `'free'` | — | `config/optimization.py` |
| `OPT_STAGE_BGE_RERANKER_V2_M3` | user | `False` | — | `config/optimization.py` |
| `OPT_STAGE_LLMLINGUA2` | user | `False` | — | `config/optimization.py` |
| `OPT_STAGE_LLMLINGUA2_RATE` | user | `0.5` | — | `config/optimization.py` |
| `OPT_STAGE_MXBAI_RERANK_BASE_V2` | user | `False` | — | `config/optimization.py` |
| `OPT_STAGE_PROVENCE` | user | `False` | — | `config/optimization.py` |
| `OPT_STAGE_PROVENCE_THRESHOLD` | user | `0.05` | — | `config/optimization.py` |
| `OPT_STAGE_RERANK_CACHE` | user | `True` | — | `config/optimization.py` |
| `OPT_STAGE_RERANK_MAX_LENGTH` | user | `1024` | — | `config/optimization.py` |
| `OPT_STAGE_SENTENCE_DEDUP_MMR` | user | `False` | — | `config/optimization.py` |
| `OPT_STAGE_SENTENCE_DEDUP_MMR_LAMBDA` | user | `0.5` | — | `config/optimization.py` |
| `OPT_STAGE_SENTENCE_DEDUP_MMR_THRESHOLD` | user | `0.85` | — | `config/optimization.py` |
| `OPT_STAGE_SPOTLIGHT_NONCE` | user | `False` | — | `config/optimization.py` |
| `OPT_STAGE_SPOTLIGHT_NONCE_MODE` | user | `'random'` | — | `config/optimization.py` |
| `OPT_STAGE_SPOTLIGHT_NONCE_SECRET` | user | `''` | — | `config/optimization.py` |
| `OPT_STRICT_GATE_RELEVANCE` | user | `True` | — | `config/optimization.py` |
| `OPT_STRICT_GATING` | user | `False` | — | `config/optimization.py` |
| `OPT_STRICT_LEXICAL_SCREEN` | user | `True` | — | `config/optimization.py` |
| `OPT_ZERO_EVIDENCE_DROP` | user | `False` | — | `config/optimization.py` |
| `OPT_ZERO_EVIDENCE_SHADOW` | user | `True` | — | `config/optimization.py` |
| `PER_SOURCE_MAX_TOKENS` | user | `1500` | Max tokens any single source may contribute to the context. | `config/retrieval.py` |
| `PORT` | user | `8000` | Port the API server listens on. | `config/benchmark.py` |
| `PPR_ALPHA` | user | `0.85` | — | `config/retrieval.py` |
| `PPR_ENABLED` | user | `False` | — | `config/retrieval.py` |
| `PPR_ITERS` | user | `30` | — | `config/retrieval.py` |
| `PPR_TOP_N` | user | `15` | — | `config/retrieval.py` |
| `PREFILTER_LEXICAL_WEIGHT` | user | `0.3` | Weight of the lexical (BM25) score relative to the graph score in the pre-filter. | `config/retrieval.py` |
| `PREFILTER_TOP_K` | user | `8` | Deterministic top-K pre-filter before the paid judge (0 = disabled, judge everything). | `config/retrieval.py` |
| `PROFILE` | user | `'production'` | Runtime profile: production \| development. | `config/benchmark.py` |
| `PYTHONIOENCODING` | sistema | — | definida pelo Gateway ao lançar subprocessos (UTF-8) | `app/services/graphify.py` |
| `PYTHONUTF8` | sistema | — | definida pelo Gateway ao lançar subprocessos (UTF-8) | `app/services/graphify.py` |
| `SHELL` | sistema | — | shell do usuário (Unix), usado para escolher o shell dos terminais | `app/terminals/profiles.py` |
| `SNIPPET_MAX_TOKENS` | user | `300` | Max tokens per emitted snippet. | `config/retrieval.py` |
| `VLLM_API_KEY` | user | — | [user] Segredo: chave do vLLM, se o servidor exigir. | `app/adapters/models/providers.py` |
| `VLLM_BASE_URL` | user | `'http://localhost:8001/v1'` | Base URL of a local vLLM OpenAI-compatible server. | `config/agents.py` |
| `XDG_DATA_HOME` | sistema | — | base XDG do diretório de dados no Linux | `config/paths.py` |
