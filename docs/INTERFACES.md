<!-- GERADO por scripts/gen_interface_docs.py (ANA-063). NÃO edite à mão: rode o script. -->
<!-- tests/test_docs_interfaces.py falha se este arquivo divergir do código. -->

# Interfaces do Anamnésia / Memory Gateway (geradas do código)

Contrato único de REST, CLI e MCP. Contexto e semântica: [README](../README.md) · [MEMORY_SEARCH_MODES](guides/MEMORY_SEARCH_MODES.md) · [SECURITY](guides/SECURITY.md).

## REST (OpenAPI 3.1.0, 119 operações)

Fonte: `app.main.create_app().openapi()`; no servidor, `/docs` e `/openapi.json`. `?` = parâmetro opcional.

| Método | Caminho | Parâmetros | Corpo | Resumo |
| --- | --- | --- | --- | --- |
| GET | `/api/alerts` | window?, tokens_pct?, latency_p95_pct?, cost_pct? | — | Alerts |
| GET | `/api/benchmark/aggregate` | range?, session_id?, include_warmup? | — | Aggregate |
| GET | `/api/benchmark/report.json` | range?, session_id?, include_warmup? | — | Report Json |
| GET | `/api/benchmark/report.md` | range?, session_id?, include_warmup? | — | Report Md |
| GET | `/api/connections` | — | — | List Connections |
| GET | `/api/connections/resilience/state` | — | — | Resilience State |
| DELETE | `/api/connections/{cid}/secret` | cid | sim | Delete Secret |
| PUT | `/api/connections/{cid}/secret` | cid | sim | Put Secret |
| GET | `/api/connections/{cid}/snippet` | cid | — | Get Snippet |
| POST | `/api/connections/{cid}/test` | cid | — | Test Connection |
| GET | `/api/costs/budget` | — | — | Get Budget |
| PUT | `/api/costs/budget` | — | sim | Put Budget |
| GET | `/api/costs/by-role` | range? | — | By Role |
| GET | `/api/costs/calls` | cursor?, limit?, project?, range? | — | Calls |
| GET | `/api/costs/calls/{run_id}` | run_id | — | Call Detail |
| GET | `/api/costs/export.csv` | range?, project? | — | Export Csv |
| GET | `/api/costs/hourly` | range?, project? | — | Hourly |
| GET | `/api/costs/routing/summary` | — | — | Routing Summary |
| GET | `/api/costs/stream` | max_seconds?, max_events?, poll_interval?, after_rowid? | — | Stream |
| GET | `/api/costs/summary` | range?, project? | — | Summary |
| POST | `/api/decision/batch` | — | sim | Batch |
| GET | `/api/decision/config` | — | — | Config |
| POST | `/api/decision/decision` | — | sim | Decision |
| GET | `/api/decision/evaluation` | — | — | Evaluation |
| GET | `/api/decision/history` | limit?, project? | — | History |
| GET | `/api/decision/metrics` | project? | — | Metrics |
| GET | `/api/decision/status` | — | — | Status |
| POST | `/api/jev/config` | — | sim | Jev Save Config |
| GET | `/api/jev/status` | — | — | Jev Status |
| POST | `/api/jev/test` | — | — | Jev Test Connection |
| GET | `/api/memory/audit` | — | — | Audit |
| POST | `/api/memory/consolidate` | — | sim | Consolidate |
| GET | `/api/memory/contradictions` | — | — | Contradictions |
| GET | `/api/memory/evidence` | file, limit? | — | Note Evidence |
| GET | `/api/memory/export` | — | — | Export Notes |
| GET | `/api/memory/export.jsonl` | — | — | Export Jsonl |
| GET | `/api/memory/feedback/events` | reviewed? | — | Feedback Events |
| POST | `/api/memory/feedback/events/{event_id}/review` | event_id | — | Review Event |
| POST | `/api/memory/forget` | — | sim | Forget |
| POST | `/api/memory/import` | overwrite? | — | Import Jsonl |
| GET | `/api/memory/last-search` | — | — | Last Search |
| GET | `/api/memory/lineage` | limit_runs? | — | Memory Lineage |
| POST | `/api/memory/migrate` | — | sim | Migrate |
| GET | `/api/memory/notes` | project?, tag?, kind?, include_expired? | — | List Notes |
| POST | `/api/memory/notes` | — | sim | Create Note |
| DELETE | `/api/memory/notes/{note_id}` | note_id | — | Delete Note |
| GET | `/api/memory/notes/{note_id}` | note_id | — | Get Note |
| PUT | `/api/memory/notes/{note_id}` | note_id | sim | Update Note |
| GET | `/api/memory/notes/{note_id}/diff` | note_id, a, b? | — | Note Diff |
| POST | `/api/memory/notes/{note_id}/feedback` | note_id | sim | Note Feedback |
| GET | `/api/memory/notes/{note_id}/history` | note_id | — | Note History |
| POST | `/api/memory/notes/{note_id}/rollback` | note_id | sim | Note Rollback |
| POST | `/api/memory/packs` | — | sim | Create Pack |
| GET | `/api/memory/packs/{pack_id}` | pack_id | — | Get Pack |
| GET | `/api/memory/packs/{pack_id}/verify` | pack_id | — | Verify Pack |
| POST | `/api/memory/reap` | — | sim | Reap |
| GET | `/api/memory/runs/{run_id}/evidence` | run_id | — | Run Evidence |
| GET | `/api/memory/runs/{run_id}/quality` | run_id | — | Run Quality |
| GET | `/api/memory/search-preview` | q, max_results?, scope?, pipeline? | — | Search Preview |
| GET | `/api/memory/trash` | — | — | Trash |
| POST | `/api/memory/trash/{trash_id}/restore` | trash_id | — | Trash Restore |
| GET | `/api/memory/usefulness` | — | — | Usefulness |
| GET | `/api/orchestration/presets` | — | — | Presets |
| GET | `/api/orchestration/runs` | path? | — | List Runs |
| POST | `/api/orchestration/runs` | — | sim | Create Run |
| GET | `/api/orchestration/runs/{run_id}` | run_id, path? | — | Get Run |
| POST | `/api/orchestration/runs/{run_id}/cancel` | run_id, path? | — | Cancel Run |
| GET | `/api/profiles` | — | — | List Profiles |
| GET | `/api/projects` | — | — | List Projects |
| POST | `/api/projects` | — | sim | Add Project |
| DELETE | `/api/projects/{project_id}` | project_id | — | Remove Project |
| GET | `/api/projects/{project_id}/file` | project_id, path | — | Project File |
| GET | `/api/projects/{project_id}/files` | project_id, path?, q?, content? | — | Project Files |
| POST | `/api/projects/{project_id}/initialize` | project_id | sim | Initialize Project |
| GET | `/api/projects/{project_id}/worktrees` | project_id | — | List Project Worktrees |
| POST | `/api/projects/{project_id}/worktrees` | project_id | sim | Create Project Worktree |
| DELETE | `/api/projects/{project_id}/worktrees/{worktree_id}` | project_id, worktree_id, confirm?, force? | — | Delete Project Worktree |
| GET | `/api/providers/health` | last_n? | — | Providers Health |
| GET | `/api/sessions` | — | — | List Sessions |
| POST | `/api/sessions` | — | sim | Create Session |
| DELETE | `/api/sessions/{session_id}` | session_id | — | Delete Session |
| GET | `/api/settings` | — | — | Get Settings |
| PUT | `/api/settings` | — | sim | Put Settings |
| POST | `/benchmark/estimate` | — | sim | Benchmark Estimate |
| GET | `/benchmark/history/summary` | — | — | Benchmark History Summary |
| GET | `/benchmark/jobs/{job_id}` | job_id | — | Benchmark Job |
| GET | `/benchmark/questions` | — | — | Benchmark Questions |
| POST | `/benchmark/run` | — | sim | Benchmark Run |
| POST | `/benchmark/run-all` | — | sim | Benchmark Run All |
| GET | `/benchmark/runs` | limit?, offset?, session_id?, agent?, q?, since?, adhoc_only?, full?, until? | — | Benchmark Runs |
| GET | `/benchmark/runs/{run_id}` | run_id | — | Benchmark Run Detail |
| GET | `/benchmark/sessions` | limit?, offset? | — | Benchmark Sessions |
| GET | `/benchmark/stats` | session_id? | — | Benchmark Stats |
| POST | `/benchmark/threshold-sweep` | — | sim | Threshold Sweep |
| GET | `/benchmark/timeseries` | metric?, agg?, since?, until?, pipeline?, max_points?, tz? | — | Benchmark Timeseries |
| POST | `/config/model-key` | — | sim | Set Model Key |
| GET | `/config/model-keys` | — | — | Get Model Keys |
| GET | `/config/optional-stages` | — | — | Get Optional Stages Config |
| POST | `/config/optional-stages` | — | sim | Set Optional Stages Config |
| GET | `/config/shell-confirm` | — | — | Config Shell Confirm |
| GET | `/config/token` | — | — | Config Token |
| POST | `/config/vault-path` | — | sim | Set Vault Path |
| POST | `/config/vault-scaffold` | — | sim | Vault Scaffold |
| GET | `/config/verdict` | — | — | Get Verdict Flag |
| POST | `/config/verdict` | — | sim | Set Verdict Flag |
| POST | `/feedback/evaluation` | — | sim | Add Evaluation |
| POST | `/feedback/false-negative` | — | sim | Mark False Negative |
| POST | `/feedback/label` | — | sim | Add Label |
| POST | `/generate` | — | sim | Generate |
| GET | `/health` | — | — | Health |
| POST | `/memory/search` | — | sim | Memory Search |
| POST | `/memory/search/baseline` | — | sim | Memory Search Baseline |
| POST | `/memory/search/graphify` | — | sim | Memory Search Graphify |
| POST | `/memory/search/graphify-jev` | — | sim | Memory Search Graphify Jev |
| POST | `/route` | — | sim | Route Decision |
| GET | `/system/info` | — | — | System Info |
| GET | `/system/integrations` | refresh? | — | Integrations |
| GET | `/system/memory` | inactive_days?, hot_min? | — | System Memory |
| GET | `/system/projects` | — | — | System Projects |

## CLI

### memory_gateway

`python -m memory_gateway` — 14 subcomandos: `search`, `benchmark`, `sweep`, `stats`, `info`, `vault-check`, `decision`, `index`, `db-maintenance`, `db-prune`, `memory-audit`, `vault-lint`, `backup-create`, `backup-restore`

#### `python -m memory_gateway search`

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `query` |  | posicional |
| `--pipeline` |  | choices: auto/baseline/graphify/graphify_jev/graphify_jev_opt/graphify_laya/graphify_laya_jev; default: auto |
| `--max-results` |  | default: 10 |
| `--jev-mode` |  | choices: performance/strict |
| `--threshold` |  | — |
| `--show-context` |  | — |
| `--json` |  | — |
| `--mode` |  | choices: context/answer/delegate; default: context |
| `--risk` |  | choices: low/medium/high; default: medium |

#### `python -m memory_gateway benchmark`

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--pipeline` |  | choices: baseline/graphify/graphify_jev/graphify_jev_opt/graphify_laya/graphify_laya_jev |
| `--questions` |  | — |
| `--agent` |  | choices: hermes/claude_code/codex/opencode/generic |
| `--provider` |  | — |
| `--model` |  | — |
| `--repetitions` |  | choices: 1/3/5/10; default: 1 |
| `--jev-mode` |  | choices: performance/strict |
| `--no-warmup` |  | — |
| `--fail-on-regression` | exit 1 se as runs recentes regrediram (tokens/latência p95/custo) contra as anteriores (ANA-202) | — |
| `--dry-run` |  | — |
| `--json` |  | — |

#### `python -m memory_gateway sweep`

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--questions` |  | — |
| `--extended` | inclui 0.10–0.40 além dos valores da spec | — |
| `--json` |  | — |

#### `python -m memory_gateway stats`

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--session` |  | — |
| `--json` |  | — |

#### `python -m memory_gateway info`

#### `python -m memory_gateway vault-check`

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--save` |  | — |
| `--compare` |  | — |

#### `python -m memory_gateway decision` — Decision Engine (ANAM-043): status \| test (itens sintéticos) \| history (IDs/hashes)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `action` |  | choices: status/test/history; posicional |
| `--provider` | test: força o provider | choices: jev/laya/hybrid/adaptive |
| `--strategy` | test: estratégia do hybrid | choices: laya_then_jev/jev_then_laya/ensemble |
| `--op` |  | choices: retrieval/memory/security; default: retrieval |
| `--project` | isolamento por projeto (limiares/cache/histórico) | — |
| `--limit` |  | default: 20 |
| `--json` |  | — |

#### `python -m memory_gateway index`

#### `python -m memory_gateway db-maintenance` — retenção opt-in de benchmark.db (dry-run por padrão; --apply altera)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--older-than-days` | idade (dias) a partir da qual limpar (padrão 90) | default: 90 |
| `--db` | caminho do banco (padrão: config) | — |
| `--apply` | executa de fato (sem isso só relata) | — |
| `--vacuum` | VACUUM após aplicar (exige --apply) | — |

#### `python -m memory_gateway db-prune` — remove runs antigas de benchmark.db (nunca as sessões protegidas)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--keep-days` | idade máxima (dias) das runs mantidas | — |
| `--keep-sessions` | session_ids (separados por vírgula) que nunca são apagados | — |
| `--dry-run` | só conta quantas runs seriam apagadas | — |
| `--vacuum` | roda VACUUM após apagar (ignora com --dry-run) | — |
| `--yes` | não pergunta confirmação (ANAM-006) | — |
| `--purge-text` | também apaga query/context/answer de runs mais velhas que DAYS (padrão: env ANAMNESIA_RUNS_TEXT_RETENTION_DAYS, 30; decisão D-4 revisável) | — |
| `--db` | caminho do banco (padrão: config) | — |

#### `python -m memory_gateway memory-audit` — inventário somente leitura da memória persistente (contagens, sem conteúdo)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--vault` | caminho do vault | — |
| `--near-dup-threshold` |  | default: 0.92 |
| `--inactive-days` | notas 'ativo' sem update há mais dias que isto entram em 'inativas' | default: 90 |
| `--hot-min` | entregas mínimas em benchmark.db para a nota ser HOT (>=) ; 1..N-1 = warm, 0 = cold | default: 5 |
| `--db` | benchmark.db lido em mode=ro para contar hot/warm/cold | — |
| `--max-runs` | limita quantas runs (0 = todas) são lidas para o hot/warm/cold | — |
| `--json` |  | — |
| `-v, --verbose` | lista os arquivos candidatos | — |

#### `python -m memory_gateway vault-lint` — lint determinístico READ-ONLY do vault (saída 1 se houver itens)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--vault` | caminho do vault (default: vault configurado no projeto) | — |
| `--max-note-chars` | limite de tamanho de nota (default 20000) | — |
| `--json` |  | — |
| `-v, --verbose` | lista todos os itens em vez do resumo por categoria | — |

#### `python -m memory_gateway backup-create` — backup (zip + sha256) de benchmark.db e do memory store

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--out` | arquivo .zip de saída | — |
| `--db` | caminho do banco (padrão: config) | — |
| `--memory-dir` | pasta do memory store (padrão: saved_context) | — |
| `--no-db` |  | — |
| `--no-memory` |  | — |
| `--force` | sobrescreve o .zip se existir | — |

#### `python -m memory_gateway backup-restore` — restaura um backup verificando sha256 (sem --force não sobrescreve)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `archive` |  | posicional |
| `--db` | destino do banco (padrão: config) | — |
| `--memory-dir` | destino do memory store (padrão: saved_context) | — |
| `--force` | permite sobrescrever destinos existentes | — |
| `--verify-only` | só valida a integridade | — |

### anamnesia

`anamnesia` — 15 subcomandos: `version`, `doctor`, `start`, `mcp`, `search`, `index`, `memory-audit`, `vault-lint`, `vault-check`, `benchmark`, `sweep`, `stats`, `info`, `db-maintenance`, `db-prune`

#### `anamnesia version` — print version

#### `anamnesia doctor` — offline environment checks + local-first grade (L0-L5)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `--json` | machine-readable output | — |

#### `anamnesia start` — start REST API + dashboard (same as python -m app.main)

#### `anamnesia mcp` — run the MCP server over stdio (same as the anamnesia-mcp script)

#### `anamnesia search` — same as `python -m memory_gateway search` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia index` — same as `python -m memory_gateway index` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia memory-audit` — same as `python -m memory_gateway memory-audit` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia vault-lint` — same as `python -m memory_gateway vault-lint` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia vault-check` — same as `python -m memory_gateway vault-check` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia benchmark` — same as `python -m memory_gateway benchmark` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia sweep` — same as `python -m memory_gateway sweep` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia stats` — same as `python -m memory_gateway stats` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia info` — same as `python -m memory_gateway info` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia db-maintenance` — same as `python -m memory_gateway db-maintenance` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

#### `anamnesia db-prune` — same as `python -m memory_gateway db-prune` (extra args are forwarded)

| Argumento | Ajuda | Detalhes |
| --- | --- | --- |
| `rest` |  | posicional |

## MCP (servidor `memory-gateway`, stdio)

Fonte: `server.list_tools()` de `app/mcp/server.py` em subprocesso, uma vez por variante.

### Tools — padrão (`MG_MCP_TOOLSET=minimal`): 1

| Tool | Parâmetros | Descrição |
| --- | --- | --- |
| `memory_search` | `query: string, pipeline?: auto\|baseline\|graphify\|graphify_jev\|graphify_jev_opt, max_results?: integer, scope?: string/null, client?: string/null, mode?: context\|answer\|delegate, budget?: integer/null, pack?: boolean` | Recupera contexto relevante da memória Obsidian do usuário para a pergunta `query`. |

### Tools — `MG_MCP_TOOLSET=full`: 7

| Tool | Parâmetros | Descrição |
| --- | --- | --- |
| `memory_benchmark` | `question_ids?: array/null, pipelines?: array/null, repetitions?: 1\|3\|5` | Executa o Memory Retrieval Benchmark (sem geração) nas perguntas do dataset. |
| `memory_get_run` | `run_id: string` | Retorna métricas, fontes e candidatos de uma execução registrada (sem o contexto completo). |
| `memory_search_baseline` | `query: string, max_results?: integer` | Busca lexical determinística (SQLite FTS5/BM25) na memória Obsidian. Sem Graphify/JEV. |
| `memory_search_graphify` | `query: string, max_results?: integer` | Busca por travessia do grafo Graphify da memória Obsidian, sem filtragem JEV. |
| `memory_search_graphify_jev` | `query: string, max_results?: integer` | Busca Graphify + filtragem de relevância JEV (contexto menor e mais focado). |
| `memory_stats` | `` | Estatísticas agregadas dos benchmarks (latência, tokens, custo, falsos negativos) por pipeline/consumidor. |

(+ as 1 tools do conjunto padrão.)

### Tools — `MG_MCP_SAVE=1` (opt-in): 3

| Tool | Parâmetros | Descrição |
| --- | --- | --- |
| `memory_feedback` | `note_id: string, verdict: useful\|wrong\|stale, reason?: string/null, client?: string/null` | Avalia uma nota salva: useful, wrong ou stale. Duas avaliações `wrong` tiram a nota do top-k padrão. |
| `memory_save` | `title: string, content: string, tags?: array/null, project?: string/null, source_agent?: string/null, kind?: string/null, ttl_days?: number/null, confidence?: number/null, source?: string/null, supersedes?: string/null, dedupe?: string/null` | Salva uma nota de contexto (decisão, fato, preferência) na memória própria do Gateway. |

(+ as 1 tools do conjunto padrão.)

### Tools — `MG_MCP_DECISION=1` (opt-in): 2

| Tool | Parâmetros | Descrição |
| --- | --- | --- |
| `decision_status` | `` | Estado do Anamnésia Decision Engine: provider ativo (padrão JEV-only), saúde de Laya/JEV, política de |

(+ as 1 tools do conjunto padrão.)
