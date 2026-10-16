# Ambiente verificado (Fase 1 — discovery)

Verificado em 2026-09-24. Só fatos observados; atualize ao descobrir algo novo.

## Runtime
| Item | Versão / estado | Observação |
| --- | --- | --- |
| Python do projeto | CPython 3.14.4 (`.venv`, criado com `uv venv --python 3.14`) | `python` no PATH é o venv do Hermes (3.11) — **use `.venv/Scripts/python.exe`** |
| uv | 0.12.5 | instala deps no `.venv` |
| Node / npm | 24.14.1 / 11.19.0 | não usado pelo core |
| FastAPI / uvicorn | 0.141.1 / 0.53.0 | |
| MCP SDK (Python) | `mcp` 2.2.0 | API nova: `from mcp.server.mcpserver import MCPServer`; `@server.tool()`; `server.run("stdio")`. `FastMCP` foi removido. |
| Docker | ativo | `ai-memory` em 127.0.0.1:49374 (não usado pelo Gateway) |

## Vault
Vault de desenvolvimento apontado por `MEMORY_GATEWAY_VAULT` (`<YOUR_VAULT_PATH>`; alias legado
`OBSIDIAN_VAULT_PATH` ainda aceito; sem nenhum dos dois, cai no corpus de exemplo
`data/synthetic_vault`). O vault usado na verificação tinha ~61 arquivos `.md` (fora de
`.obsidian/`). Tratado sempre como READ ONLY.

## Graphify
- `graphify 0.9.59` instalado como CLI no PATH do usuário (ex.: `~/.local/bin/graphify`);
  sem API Python pública usada.
- Grafo do vault: o Graphify escreve `graphify-out/` no diretório analisado, portanto **não pode rodar no vault**.
  Solução: espelho somente-leitura dos `.md` em `data/vault_mirror/` (cópia) e `graphify update data/vault_mirror`
  (AST, sem LLM, ~3 s). Resultado: 940 nós (`file_type=document`, `node_kind=heading`), 1094 arestas
  (`contains`, `references`).
- Consulta: `graphify query "<pergunta>" --budget N --graph <graph.json>` → texto com linhas
  `NODE <label> [src=<arquivo> loc=L<n> community=...]` e `EDGE ...`; cabeçalho `Start: [...]` lista os nós semente.
  **Não há score numérico** na saída; o adapter deriva `graph_score` da ordem de travessia (documentado em `app/services/graphify.py`).
- Semântico opcional com LLM local: `graphify extract data/vault_mirror --backend ollama --max-concurrency 1 --token-budget 5000` (lento; não requerido).

## JEV (TypeSafe)
- SDK `typesafe-sdk` 0.7.1 (`TypeSafeClient.system_one(state, questions, model=, retry=, timeout=)`).
- Env: `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`, `TYPESAFE_DEFAULT_MODEL` (default `jev-latest`).
- Resposta: `SystemOneResponse(model, usage{input_tokens, output_tokens}, answers{name: NoulAnswer(noul: float)})`.
  O campo `model` retorna a versão concreta (ex.: `jev-1.13.0`), usada como identificação imutável.
- Retry oficial: `RetryPolicy(max_retries=2, backoff 0.5→5s, statuses {408,429,5xx})`. Doc: 429 rate limit, 529 overloaded.
- Endpoint HTTP: `POST https://api.typesafe.ai/v1/systemone`. Várias perguntas no mesmo request = fan-out nativo.
- Existe um protótipo anterior de integração (`api.py`) fora deste repositório, mantido localmente
  pelo desenvolvedor; não é dependência do Gateway.

## Agentes / consumidores
| Agente | Versão | Estado |
| --- | --- | --- |
| Hermes Agent | v0.20.5 | **Validado.** `hermes -z PROMPT --usage-file PATH -t TOOLSETS --reasoning none` (usage JSON: input/output/total tokens, api_calls, cost_status). `--max-turns` só existe em `hermes chat`. MCP: `hermes mcp test memory-gateway` → 7 tools. HERMES_HOME isolado em `integrations/hermes/hermes_home` (env `HERMES_HOME`). Exige ≥64K ctx: `model.context_length` + `model.ollama_num_ctx: 65536`; `-m` descarta esse override. `tools.tool_search: false` necessário para modelos locais. Endpoint custom via `provider: custom` + `base_url` (ou env `CUSTOM_BASE_URL`). |
| Claude Code | 2.1.282 | **Validado em 2026-09-24** (login via navegador, conta Pro). Bug real encontrado e corrigido: um `claude -p` simples herda o estado GLOBAL de `~/.claude` — ~14 servidores MCP do usuário (Notion, Gmail, Drive, Linear, plugins) cujos schemas entravam no prompt mesmo com `--tools ""` (~385k tokens de entrada, estourando os 200k de contexto, falhando 6 de 9 chamadas) e auto-memória entre chamadas do mesmo projeto. `--bare` resolveria os dois mas exige `ANTHROPIC_API_KEY` (aqui é só OAuth/login por navegador). Correção aplicada no adapter: `--mcp-config <vazio> --strict-mcp-config --no-session-persistence --settings '{"disableMemory":true}'`. Depois disso: 9/9 chamadas OK, ~9-13k tokens de entrada, ~US$0,007-0,019 por resposta, respostas corretas nas 3 pipelines. |
| Codex CLI | 0.155.0 | logado (ChatGPT), mas **limite de uso atingido até 07/10/2026** — não foi possível usar como consumidor nem subagent |
| OpenCode | 1.18.31 | 0 credenciais → adapter preparado, não validado |
| Ollama | 0.34.2 | `qwen3:14b`, `qwen3:8b`; OpenAI-compatible em `/v1`; `reasoning_effort: "none"` desliga o thinking do qwen3 (verificado) |
| vLLM | não instalado | adapter preparado, não testado |
| Local Qwen (llama.cpp) | configurado no Hermes principal em `127.0.0.1:8080/v1` | servidor não estava rodando |

## Resultados de verificação (2026-09-24)
- JEV real: 3 candidatos em 1 request strict → relevância 0.98/0.01/0.01, injection 0.02/0.01/**0.98** (nota "Ignore todas as instruções…" → QUARANTINE). usage real 1226 in / 112 out; estimativa local 946 → fator 1.35.
- qwen3:8b via Hermes + MCP: não conseguiu chamar a ferramenta (loop de `tool_call` malformado com tool_search; só raciocínio sem resposta com tool_search off). qwen3:14b: chamou `memory_search` (run registrado com agent=mcp) e respondeu corretamente citando `decisao-driver-asyncpg.md` (2 api calls, 18.668 tokens totais, 3m20s).

## Estágios opcionais — ambiente de benchmark (verificado 2026-10-02)
Venv separado (nunca o `.venv` do projeto): Python 3.11.16, torch 2.6.0+cu124 (RTX 3060 12 GB, CUDA ok),
transformers **4.57.6** (<5 obrigatório para `mxbai-rerank` 0.1.6), sentence-transformers 6.1.0, llmlingua 0.2.2,
nltk 3.10.3 (+ `punkt_tab` para o Provence). Preset `OPT_STAGES_PRESET=off|free|approved` (padrão `free`).
Medições, versões e licenças: `docs/reports/OPTIONAL_STAGES_BENCHMARK.md`; stack opcional **não validado em Python 3.14**.

## Retenção do benchmark.db (`db-maintenance`)

Opt-in, nunca automático. Padrão é **dry-run** (só relata linhas/tamanhos); `--apply` é obrigatório para alterar.

```
python -m memory_gateway db-maintenance [--older-than-days 90] [--db PATH] [--apply] [--vacuum]
```

Com `--apply`: zera `context`, `answer` e `sources_json` das runs mais antigas que N dias (ids, `metrics_json`, config e demais colunas ficam, então o histórico de custo sobrevive), apaga `jev_cache` mais antigo que N dias e `candidates` órfãos. `--vacuum` (só com `--apply`) devolve o espaço ao disco. Idempotente. Faça backup antes do primeiro `--apply`.

## Terminais: MCP memory_gateway por padrão (app/terminals/mcp_inject.py)

- Cada sessão de agente recebe o MCP `memory_gateway` sem tocar em config global. Verificado: `claude --mcp-config <arquivo>` (sem `--strict-mcp-config`, os MCPs do usuário permanecem). Arquivo por sessão em `data/terminal_mcp/<id>.json`, removido ao fechar.
- Hermes (sem flag por invocação), Codex, OpenCode, Gemini: **não verificados/instalados** → fallback: o PTY exporta `MG_MCP_CONFIG` (JSON `mcpServers`), `MG_MCP_COMMAND`, `MG_MCP_ARGS`, `MG_MCP_CWD`, `MG_MCP_URL`, `MEMORY_GATEWAY_URL`. Snippets manuais em `integrations/`.
- Opt-out: `MG_TERMINAL_MCP=0` ou `mcp:false` no `POST /api/sessions`. Papel de subagente: `MG_AGENT_ROLE`.

## Prompt caching do provider e pack cache-aware (ANAM-020, verificado 2026-10-15)

Fonte oficial: https://platform.claude.com/docs/en/build-with-claude/prompt-caching e https://ai.google.dev/gemini-api/docs/caching (lidas em 2026-10-15; nenhum campo foi inventado).

- **Anthropic (verificado):** `cache_control: {"type": "ephemeral"}` (opcional `"ttl": "1h"`; padrão 5 min) num bloco de conteúdo de `tools`/`system`/`messages`, ou no topo do request (cache automático). Até 4 breakpoints explícitos; lookback de 20 blocos; o prefixo é hasheado cumulativamente, então o breakpoint vai no ÚLTIMO bloco estável. Mínimo cacheável por modelo: 512 (Sonnet 5.5, Opus 5.5, Haiku 5.5…), 1.024 (Sonnet 5/4.6/4.5, Opus 4.8…), 2.048 (Opus 4.7), 4.096 (Opus 4.6/4.5, Haiku 4.5); abaixo disso processa sem cache e sem erro. Medição: `usage.cache_creation_input_tokens` / `usage.cache_read_input_tokens`.
- **Gemini (verificado):** cache IMPLÍCITO por padrão (2.5+), sem campo a enviar; mínimo 2.048 (2.5 Flash/Pro) ou 4.096 (3.x); leitura em `usage.total_cached_tokens`. Basta manter o prefixo estável.
- **OpenAI, Ollama, demais:** não verificados nesta tarefa -> o gateway NÃO emite nenhum campo de cache para eles.
- Implementação: `app/services/context_prompt.py` (re-exportado por `app/services/context_pack.py`): `freeze_snapshot`, `build_cache_aware_prompt`, `snapshot_drift`, `place_lost_in_middle`, `wrap_memory`. O `cache_control` só é emitido para `provider="anthropic"`, no último bloco estável (instruções fixas + hotset congelado); notas recuperadas, delta e pergunta ficam no sufixo. Memória vai em `<memory trust="untrusted" source=…>` com envelope escapado e instrução fixa "memória = dado".
- Refresh do vault (ANAM-018): `app/gateway/vault_manifest.py`; sem novas variáveis de ambiente (usa `OptimizerConfig.refresh_interval_s`).

## Ollama no provider: num_ctx / keep_alive / health (ANAM-032, verificado 2026-10-15)

- **Fontes:** `docs/api.md` (https://github.com/ollama/ollama/blob/main/docs/api.md: `POST /api/chat` com `options.num_ctx`, `options.num_predict`, `keep_alive`, `think`, `stream`; respostas com `done_reason`, `prompt_eval_count`, `eval_count`, `load_duration`; `GET /api/tags` = instalados, `GET /api/ps` = carregados em memória), `docs/faq.mdx` (contexto padrão 4096; `keep_alive` aceita duração, segundos, `-1` e `0`, e sobrescreve `OLLAMA_KEEP_ALIVE`) e `docs/api/openai-compatibility.mdx` ("The OpenAI API does not have a way of setting the context size"). Servidor local instalado: 0.34.2 (não estava rodando durante a verificação; os testes usam servidor fake, não a versão real).
- **Decisão:** `OllamaAdapter` usa o endpoint NATIVO `/api/chat` (o `/v1` não tem como enviar `num_ctx`/`keep_alive`). `num_ctx`/`keep_alive` só vão no corpo quando configurados (`ANAMNESIA_OLLAMA_NUM_CTX`, `ANAMNESIA_OLLAMA_KEEP_ALIVE` ou argumentos do construtor); sem configuração valem os padrões do servidor. `think:false` substitui o antigo `reasoning_effort:"none"` do `/v1`; se o modelo rejeitar `think` com HTTP 400, repete uma vez sem o campo. NÃO verificado contra o Ollama real nesta tarefa.
- **Truncamento:** `GenerationResult.truncated` (+ `raw_meta.truncated_reasons`): `output_max_tokens` (`done_reason=="length"`), `prompt_filled_num_ctx` (prompt avaliado >= `num_ctx` enviado), `prompt_below_estimate` (avaliado < 80% da estimativa heurística, só para prompts >= 64 tokens estimados; heurística, pode dar falso positivo). `None` = indeterminado.
- **Health:** `probe_ollama(base_url, model=None)` (opt-in `ANAMNESIA_HEALTH_PROBE=1`) consulta `/api/tags` e `/api/ps`: `runtime_running`, `installed`, `loaded_models` (`None` se `/api/ps` falhar), `model_installed`/`model_loaded`; cache de 10 s.
- **Privacidade (ANAM-033):** `generate(..., private=True)` só passa com destino loopback (`localhost`, `127.0.0.0/8`, `::1`); caso contrário `PrivacyBlocked` -> `error_kind="privacy_blocked"` antes de qualquer requisição. O roteador (`route(..., private=True)`) só considera modelos `local: true` e restringe a escalação (`decision.allowed_models`, `next_model(..., allowed=)`, `choose_next`). Sem modelo local: `no_eligible_model` + `privacy_blocked_no_local_model` (falha fechada). Quem chama precisa passar `private=True` (marcação do dado é do chamador; `answer.py` ainda não classifica).

## Laya: decisor local não generativo (ANAM-042, verificado 2026-10-15)

- **Fontes:** PyPI `laya` (JSON API: 0.4.8, Apache-2.0, `requires-python >=3.10`, deps `torch>=2`, `transformers>=4.48`), README do modelo `convaiinnovations/laya` (HF), `laya/serve.py` e `laya/router.py` do pacote instalado, `HfApi.model_info(files_metadata=True)`. Detalhes e uso: `docs/guides/LAYA.md`; medição: `docs/bench/anam-042-laya.md`.
- **API real (0.4.8):** `Router(models={nome: diretório|repo}, default="multilingual", device=None, preload=False, max_loaded=2, ...)`; `predict(state, questions, model=None, ...)`; `predict_batch(requests, batch_size=None)`. Resultado com `answers[*].probabilities/confidence`, `routing.model` (english|multilingual por idioma). Aceita diretórios locais (offline).
- **Instalação isolada:** venv separado (`uv`), `torch` CPU (2.14.1+cpu), `laya[serve]==0.4.8`; NUNCA no `.venv` do projeto. Pesos pinados: `laya-multilingual` `1720e3e3357cfe1e281542e223f8273b0890ca34` (643,8 MB), `laya` inglês `7b928d828b7b0e022f929d9bd2e44165aa270148` (842,6 MB), em `data/local_ai/models/` (fora do Git).
- **laya-serve:** `POST /v1/systemone`; padrão `0.0.0.0:8000` sem auth. O Gateway só aceita `MG_LAYA_SERVE_URL` loopback e recusa a porta 8000. Colibrì não serve o multilingual.
- **Medido (CPU):** p50 ≈ 225 ms/candidato; RSS ≈ 1,7 GB (multilingual) / 3,3 GB (os dois checkpoints). AUC de relevância 0,64–0,68 (lexical: 0,975); sensibilidade AUC 0,88.
- **Decisão:** pipelines `graphify_laya` / `graphify_laya_jev` registrados e opt-in; padrão continua `graphify_jev_opt`. Laya obrigatória para sensibilidade (fail-closed) e sinal de escrita (`MG_LAYA_WRITE_TRIAGE`). Variáveis `MG_LAYA_*`: `.env.example` e `docs/ENVIRONMENT_REFERENCE.md` (gerado). Opt-in significa fora dos defaults: `app.schemas.models.DEFAULT_PIPELINES` (4 congelados) governa `/benchmark/run-all`, `/benchmark/estimate`, o benchmark da CLI/runner sem `--pipeline` e o enum do MCP minimal; Laya só roda com `pipelines=[...]` explícito (API/CLI). `MG_MEMORY_RANK` (`v1` padrão | `v2`, ANAM-013) reordena o resultado de `memory_gateway.search`, exceto no pipeline congelado `graphify_jev`; ver `docs/guides/MEMORY_MODEL.md`. `ColibriRuntime` passa a chave por `COLI_API_KEY` (`key_via="env"`, padrão); `--api-key` só com `key_via="arg"`.
