# Memory Gateway

Serviço local e **independente de agente** que recupera contexto do vault Obsidian
(`C:\Users\fonse\Cérebro_AI`, somente leitura) e compara experimentalmente três pipelines
de retrieval — **Baseline**, **Graphify** e **Graphify + JEV** — com métricas persistidas em SQLite.

Especificação: `C:\Users\fonse\Cérebro_AI\30-Projetos\Memory_Gateway\memory-gateway-benchmark-prompt.md`.
Ambiente verificado: `docs/ENVIRONMENT.md`. Regras para agentes: `AGENTS.md` / `CLAUDE.md`.

## Arquitetura

```
 Hermes ─┐  Claude Code ─┐  Codex ─┐  OpenCode ─┐  qualquer cliente
         └───── MCP (stdio) ─── REST (:8000) ─── CLI ─────┘
                               │
                        MEMORY GATEWAY  (app/gateway/memory_gateway.py)
             Retrieval router · dedup · token budget · métricas · SQLite
            ┌──────────────────┼──────────────────────┐
        BASELINE           GRAPHIFY              GRAPHIFY + JEV
     SQLite FTS5/BM25   graphify query (CLI)   graphify → dedup → JEV Noul (lote)
                                               → roteamento em código → nota completa
                               │
                  ModelContextBuilder (neutro de consumidor)
                               ▼
                 contexto filtrado → agente / modelo
```

Responsabilidades: Obsidian = fonte · Graphify = recuperação · JEV = julgamento ·
Gateway = orquestração · MCP/REST/CLI = interface · agentes = consumidores · LLM = síntese · SQLite = histórico.
Nada no core importa ou depende de Hermes/Claude Code; eles são adapters em `app/adapters/agents/`.

## Instalação

```powershell
cd C:\Users\fonse\Projetos_AI\Memory_Gateway
uv venv --python 3.14 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
copy .env.example .env     # preencher TYPESAFE_API_KEY
.venv\Scripts\python.exe -m memory_gateway index   # espelha o vault e constrói o grafo
.venv\Scripts\python.exe -m app.main               # REST + frontend
```

Ao iniciar, o servidor mostra `Local: http://127.0.0.1:8000` e `Network: http://<IP>:8000`.
Para acesso pela rede, o Windows pode exigir uma regra de firewall (não é criada automaticamente):
`netsh advfirewall firewall add rule name="Memory Gateway 8000" dir=in action=allow protocol=TCP localport=8000`.

> Atenção: `python` no PATH desta máquina é o venv do Hermes (3.11). Use sempre `.venv\Scripts\python.exe`.

## Vault (READ ONLY)

- Único acesso: `app/services/obsidian.py` — valida que o caminho está dentro do vault e que a
  operação ∈ `READ_ONLY_OPERATIONS = {list, read, stat, hash}`. Não existe função de escrita.
- Banco, logs, cache e grafo ficam em `benchmark.db`, `logs/`, `data/` — nunca no vault.
- Prova: `python -m memory_gateway vault-check --save data/antes.json` e depois `--compare data/antes.json`
  (sha256 de cada `.md`; sai com código 1 se algo mudou).

## Pipelines

| | Baseline | Graphify | Graphify + JEV |
| --- | --- | --- | --- |
| Candidatos | SQLite FTS5 `bm25()`, tokenizer `unicode61 remove_diacritics 2`, termos OR sem stop-words, seção com peso 2x | `graphify query "<q>" --budget 6000 --graph data/vault_mirror/graphify-out/graph.json` | igual ao Graphify |
| Pós-processamento | limpeza, snippet ≤ 300 tokens, sha256 do texto normalizado, dedup por hash / (arquivo, seção, snippet), 1 por nota | idem | idem |
| Filtro | — | — | **pré-filtro determinístico (0 tokens)** → JEV Noul `is_relevant` (+ `contains_instruction_injection` em `strict`) em **uma requisição por lote**; KEEP/REVIEW/DROP/QUARANTINE decididos em código |
| Contexto | `ModelContextBuilder`: relevância → score → round-robin por arquivo → `MODEL_CONTEXT_BUDGET` | idem | sobreviventes recebem a **nota completa** (seção relevante primeiro), limitada a `PER_SOURCE_MAX_TOKENS` |

### Qual pipeline usar (medido, não teórico)

Auditoria de 2026-09-27 sobre 170 runs reais (`python scripts/audit_pipeline.py`), medianas:

| | Baseline | Graphify | Graphify + JEV |
| --- | --- | --- | --- |
| Contexto final (tokens) | 2.088 | 1.919 | 483 |
| **Tokens totais gastos/query** | **2.088** | **1.919** | **20.530** |
| Recall (ground truth no contexto) | **1,000** | 0,800 | 0,600 |
| Latência total | **16 ms** | 627 ms | 1.167 ms |

**O Baseline é o padrão** porque ganha em recall, latência e custo simultaneamente. O `graphify_jev`
reduz o contexto final em 77% mas gasta ~10x mais tokens *no total*, porque paga o juiz para
avaliar ~50 candidatos e manter 1. Detalhes e causa-raiz: `30-Projetos/Memory_Gateway/` no vault.
`graphify` e `graphify_jev` continuam disponíveis como opções experimentais medidas, não como padrão.

### Pré-filtro determinístico (`app/services/prefilter.py`)

Corte top-K **antes** do juiz pago, custo zero em tokens. Ordena por híbrido de
(percentil de rank do score do Graphify, com empates mediados) + (sobreposição lexical dos termos
da query contra caminho, heading e snippet da nota, sem acentos e sem stop-words).

- `PREFILTER_TOP_K` (padrão 25; `0` desliga e volta ao comportamento anterior)
- `PREFILTER_LEXICAL_WEIGHT` (padrão 0.3)

Medido nos 42 runs gravados: K=25 retém 91,7% dos sobreviventes do JEV com metade da entrada.
Verificado ao vivo contra a API real do JEV: entrada do juiz caiu de 19.391 → 10.342 tokens (-47%)
mantendo a nota correta. **Armadilha registrada**: a primeira versão normalizava com min-max, o que
dava 1,0 a todos os empatados e deixava 29 notas irrelevantes empatadas derrubarem a nota cujo nome
batia com a query — um teste unitário pegou isso; hoje usa percentil de rank com empates mediados.

### Métricas honestas de custo

`context_reduction` isolado **engana**: ele caía 77% enquanto o custo total subia 10x. Por isso todo
run agora grava também:

- `judge_tokens` — tokens gastos pelo juiz (JEV)
- `total_tokens_spent` = `judge_tokens + context_tokens` — o custo real por query
- `token_amplification` = `total_tokens_spent / context_tokens` — `> 1` significa que o pipeline
  gasta mais do que entrega como contexto (medido: 22,41 no `graphify_jev`)

## Memória multiprojeto (global vs. por projeto)

Projetos e áreas são **descobertos dos caminhos do vault**, sem nenhum nome fixo no código: criar
`30-Projetos/<Novo_Projeto>/` faz o projeto aparecer sozinho (`app/services/scope.py`).

`GET /system/projects` → `{total_notes, areas{}, projects[{slug, display_name, area, note_count}]}`

Toda busca aceita `scope`, aplicado **antes do juiz** (escopo estreito custa menos tokens) e
reaplicado antes de montar o contexto (defesa em profundidade contra vazamento entre projetos):

| `scope` | Busca |
| --- | --- |
| omitido / `global` | cérebro inteiro |
| `projeto:norteia` | um projeto |
| `projeto:norteia,projeto:memory-gateway` | vários projetos (união) |
| `area:50-Pessoal` | uma área |

```bash
curl -X POST localhost:8000/memory/search/baseline -H "Content-Type: application/json" \
  -d '{"query":"decisao driver postgres","scope":"projeto:norteia"}'
```

Cada run grava `scope` e `documents_out_of_scope`. Convenção de layout em `PROJECT_AREAS`
(`app/services/scope.py`): só subpastas de `30-Projetos/` são projetos — `50-Pessoal/perfil/` e
`50-Pessoal/preferencias/` são pastas organizacionais, não projetos.

### Graphify

O Graphify 0.9.59 grava `graphify-out/` dentro do diretório analisado, então **não pode rodar no vault**
(decisão já registrada no Cérebro: `decisao-graphify-out-fora-do-vault`). O Gateway mantém uma cópia
somente-leitura dos `.md` em `data/vault_mirror/` e roda `graphify update` (só AST, sem LLM, ~3 s).
A CLI não expõe score numérico; o `graph_score` vem da ordem da travessia BFS (sementes = 1,0; demais caem
linearmente até 0,3). Um nó de heading sem corpo (ex.: o H1 da nota) é expandido com as seções seguintes.

### JEV (TypeSafe `typesafe-sdk` 0.7.1, modelo `jev-1.13.0`)

- Estado mínimo: `state={"query"}`; cada candidato vai nas `instructions` do seu Noul com somente
  `id, source, section, snippet, graph_score`.
- **Lotes adaptativos**: enche o lote até `JEV_CONTEXT_BUDGET` (padrão 48k; limite documentado: 64k por request)
  usando uma estimativa determinística com fator de segurança 1,35 (medido contra `usage.input_tokens` real).
- Modos: `performance` (só relevância, padrão) e `strict` (relevância + injection **na mesma requisição**).
- Thresholds centralizados (`config/jev.py`): KEEP ≥ 0,78; REVIEW ≥ 0,55; DROP < 0,55; QUARANTINE se injection ≥ 0,80.
  `JEV_REVIEW_ACTION=keep` (padrão) ou `drop`. `JEV_FAILURE_MODE=fail_open|fail_closed`.
- `JEV_SECOND_PASS` (só REVIEW) e `JEV_CONTRADICTION_CHECK` preparados, desligados por padrão. `Choice`/`Score` não são usados.
- Retry: `RetryPolicy` oficial do SDK (429/5xx, backoff). O SDK 0.7.1 não expõe a contagem de retries → `retry_count = null`.
- Versões registradas por run: `jev_model` pedido, `jev_model_resolved` (resposta da API), `jev_sdk_version`,
  `jev_prompt_version`, `jev_config_version`.
- Cache (`jev_cache` no SQLite, chave = hash(query, candidate_id, content_hash, jev_model, prompt_version, mode)):
  ligado em `PROFILE=production`, **sempre desligado** em benchmark (`cache_enabled=false` gravado no run).

## Interfaces

### MCP (preferencial para agentes)

`.venv\Scripts\python.exe -m app.mcp.server` (stdio, SDK `mcp` 2.2 `MCPServer`). Ferramentas, todas só leitura:
`memory_search`, `memory_search_baseline`, `memory_search_graphify`, `memory_search_graphify_jev`,
`memory_benchmark`, `memory_get_run`, `memory_stats`. Teste: `.venv\Scripts\python.exe scripts\mcp_smoke.py`.

### Hermes (consumidor de primeira classe)

`integrations/hermes/hermes_home/config.yaml` é um **HERMES_HOME isolado** (não toca no perfil real do usuário)
com o MCP `memory-gateway`, modelo local `qwen3:14b` via Ollama e:
- `context_length` / `ollama_num_ctx: 65536` — o Hermes exige ≥ 64K de contexto;
- `tools.tool_search: false` — com o bridge `tool_search/tool_call` padrão, o qwen3:8b entrou em loop de
  chamadas malformadas (23 api calls, observado).

```bash
export HERMES_HOME=C:/Users/fonse/Projetos_AI/Memory_Gateway/integrations/hermes/hermes_home
hermes mcp test memory-gateway
hermes -z "Chame memory_search com query='...' e responda citando a nota" --reasoning none -t memory-gateway --usage-file uso.json
```

Para ligar no **seu** Hermes principal, adicione ao `C:\Users\fonse\AppData\Local\hermes\config.yaml`:
```yaml
mcp_servers:
  memory-gateway:
    command: C:\Users\fonse\Projetos_AI\Memory_Gateway\.venv\Scripts\python.exe
    args: [-m, app.mcp.server]
    cwd: C:\Users\fonse\Projetos_AI\Memory_Gateway
    connect_timeout: 60
    timeout: 300
```
(não foi alterado automaticamente). Alternativa HTTP: `POST http://127.0.0.1:8000/memory/search`.

### Claude Code / Codex / OpenCode

- **Claude Code: validado em 2026-09-24** (login via navegador, conta Pro). O adapter (`app/adapters/agents/agents.py`)
  isola cada chamada do estado global do usuário: config MCP vazia + `--strict-mcp-config`, `--no-session-persistence`
  e `disableMemory` — sem isso, os ~14 MCPs globais do usuário e a auto-memória do projeto inflam o prompt a ~385k
  tokens e contaminam repetições do benchmark (ver `docs/ENVIRONMENT.md`).
- Codex: `[mcp_servers.memory-gateway]` em `~/.codex/config.toml`; adapter via `codex exec --json`.
- OpenCode: detectado, sem credenciais → adapter preparado, **não validado**.

### REST

`GET /health` · `POST /memory/search` · `POST /memory/search/{baseline,graphify,graphify-jev}` ·
`POST /benchmark/run` · `POST /benchmark/run-all` · `POST /benchmark/estimate` · `GET /benchmark/jobs/{id}` ·
`POST /benchmark/threshold-sweep` · `GET /benchmark/runs` · `GET /benchmark/runs/{run_id}` · `GET /benchmark/sessions` ·
`GET /benchmark/stats` · `POST /feedback/false-negative` · `POST /feedback/label` · `POST /feedback/evaluation` ·
`GET /system/info` · `GET /system/integrations`. Docs interativas: `/docs`.

### CLI

```powershell
.venv\Scripts\python.exe -m memory_gateway search "Como foi definida a arquitetura do Norteia?" [--pipeline baseline|graphify|graphify_jev] [--show-context] [--json]
.venv\Scripts\python.exe -m memory_gateway benchmark                          # retrieval-only, 3 pipelines, dataset completo
.venv\Scripts\python.exe -m memory_gateway benchmark --pipeline graphify_jev
.venv\Scripts\python.exe -m memory_gateway benchmark --agent hermes --questions q02 q08    # end-to-end
.venv\Scripts\python.exe -m memory_gateway benchmark --agent generic --provider ollama --model qwen3:8b
.venv\Scripts\python.exe -m memory_gateway benchmark --dry-run --repetitions 3            # estimated_runs
.venv\Scripts\python.exe -m memory_gateway sweep [--extended]
.venv\Scripts\python.exe -m memory_gateway stats [--session <id>]
.venv\Scripts\python.exe -m memory_gateway info | index | vault-check
```

## Benchmark

- Unidade: pergunta + pipeline + agente + modelo + configuração. Dataset: `benchmark/questions.json`
  (12 perguntas reais: projetos, decisões, programação, conceitos, ferramentas, erros, cruzamento, 2 sem resposta),
  com `expected_sources` → métrica `expected_sources_found.recall` por run.
- **Retrieval-only** (sem geração) e **end-to-end** (retrieval + JEV + geração por UM consumidor por vez).
  Dentro de um consumidor, prompt/modelo/parâmetros são idênticos; só o retrieval muda. Prompt único neutro:
  `app/gateway/context_builder.py::CONSUMER_PROMPT_TEMPLATE`.
- Ordem dos pipelines aleatória por pergunta (seed registrada), warm-up fora das estatísticas,
  repetições 1/3/5/10 com mean/median/p95/min/max/std, cache desligado.
- Consumidores não são misturados automaticamente: você escolhe quais participam.
- Threshold sweep: o JEV é chamado **uma vez** por pergunta e o roteamento é reaplicado em código para cada limiar.

### Tokens e custos

Separados em: `candidate_tokens_before_filter`, `context_tokens`, `jev_input_tokens`/`jev_output_tokens` (reais, da API),
`model_input_tokens`/`model_output_tokens` (reportados pelo provedor), `agent_tokens` (total do agente, com system prompt
e ferramentas) e `agent_overhead_tokens`. Preços apenas verificados (`config/pricing.py`): JEV US$ 0,042/Mtok de entrada,
saída gratuita; modelos locais = 0. Preço ou token desconhecido → `null` ("unavailable"), nunca estimado.
`break_even()` reporta overhead do JEV, economia de contexto, `net_cost_change` e `net_latency_change` — sem veredito.

### Auditoria determinística do pipeline (0 tokens de LLM)

```powershell
.venv\Scripts\python.exe scripts\audit_pipeline.py          # tabela legível
.venv\Scripts\python.exe scripts\audit_pipeline.py --json    # para automação
```

Lê `benchmark.db` em modo somente-leitura e regenera o funil completo por pipeline: candidatos
recuperados → removidos por dedup → tokens de candidato → enviados ao juiz → tokens do juiz →
mantidos/descartados → sobreviventes → **contexto final**, mais latência por etapa, custo,
eficiência e duplicação. É a forma barata de reauditar o sistema sem gastar um único token de
modelo — rode isso antes de tirar qualquer conclusão sobre performance.

Ao ler a saída: `context_reduction` alto **não** significa economia. Compare sempre com
`total_tokens_spent` e `token_amplification`.

### Feedback humano

No frontend (Histórico → run): **Mark as False Negative** em candidatos descartados, avaliação 1–5
(accuracy, completeness, groundedness, citation_quality) e rótulos de retrieval. `false_negative_rate` = marcados / descartados.

## Testes

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```
Sem rede e sem chaves: fakes para JEV, Graphify, providers e Hermes. Cobre dedup, token budget, roteamento por threshold,
parsing/lotes do JEV, seleção de pipeline, proteção read-only, schema MCP, endpoints REST, métricas e custos.

## Estrutura

```
app/          main.py · config.py · api/ · mcp/ · cli/ · gateway/ · retrieval/ · services/ · adapters/ · benchmark/ · database/ · schemas/
config/       retrieval.py · jev.py · agents.py · pricing.py · benchmark.py
benchmark/    questions.json
frontend/     index.html · app.js · style.css
integrations/ hermes/hermes_home/config.yaml
memory_gateway/  entrypoint da CLI
tests/ · scripts/ · docs/ · logs/ · data/ · benchmark.db
```

## Troubleshooting

| Sintoma | Causa / solução |
| --- | --- |
| `ModuleNotFoundError: typesafe_sdk` | usando o `python` do Hermes; use `.venv\Scripts\python.exe` |
| Graphify sem resultados | `python -m memory_gateway index` para reconstruir o espelho e o grafo |
| Hermes: "context window of 40,960 … minimum 64,000" | usar o HERMES_HOME isolado **sem** `-m` (o `-m` descarta o override de contexto) |
| Hermes só "internal reasoning", sem resposta | qwen3:8b; use qwen3:14b (default do HERMES_HOME isolado) com `--reasoning none` |
| JEV 429/529 | o SDK faz retry com backoff; contadores em `metrics.jev.rate_limit_count/overload_count` |
| Acesso pela rede não abre | regra de firewall acima |
| Qwen3 via Ollama direto gasta tokens pensando | o adapter envia `reasoning_effort: "none"` |
