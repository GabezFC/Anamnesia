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
Medições, versões e licenças: `docs/OPTIONAL_STAGES_BENCHMARK.md`; stack opcional **não validado em Python 3.14**.
