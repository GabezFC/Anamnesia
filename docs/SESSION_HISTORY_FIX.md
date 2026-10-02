# Histórico de sessões — causa raiz e correção (M1)

## Sintoma
O painel "Sessões" parecia terminar em 27/09/2026 e "Runs brutos" não mostrava tudo, embora o banco
tivesse runs até 01/10/2026.

## Cadeia investigada (banco real, somente leitura)
| Etapa | Verificação | Resultado medido |
| --- | --- | --- |
| 1. As runs novas existem? | `runs` agrupado por dia local | 24/09=164, 27/09=5.836, 28/09=10, 29/09=1, 30/09=1, 01/10=2 (total 6.014) |
| 2. Estão persistidas? | `created_at` da última run | 01/10/2026 19:19:08 (epoch REAL em segundos) |
| 3. Em que sessão? | `session_id` | todas `adhoc` (MCP/REST) |
| 4. Por que a sessão fica velha? | `Database.create_session` usa `INSERT OR IGNORE` | `adhoc.created_at` = 24/09/2026 21:36 para sempre |
| 5. Por que some do topo? | `list_sessions` ordenava por `sessions.created_at DESC` | `adhoc` ia para o fim, datada de 24/09 |
| 6. Por que "runs brutos" é incompleto? | frontend carrega `RUN_LIMIT=5000` | 6.014 − 5.000 = 1.014 runs antigas fora, sem aviso |
| 7. "Atualizar" invalida o cache? | `cached()` em `api.js` | não: só a tabela de runs era refeita; o preload ficava memoizado |

## Causa raiz
Não era perda de dados. (a) a ordenação/exibição de sessões usava a data de *criação da linha*, não a
última atividade; (b) os gráficos dependiam de um preload truncado em 5.000 runs.

## Correção
- `Database.list_sessions(limit, offset)`: agrega `runs` (GROUP BY `session_id`) e devolve
  `first_run_at`, `last_run_at`, `runs`; ordena por `COALESCE(last_run_at, created_at) DESC`; inclui
  `session_id` que só existem em `runs`. Índice novo `runs_session_created`. Timestamps gravados não mudam.
  `GET /benchmark/sessions` aceita `limit/offset` e devolve `X-Total-Count`.
- `GET /benchmark/history/summary`: total de runs/sessões, mais antiga/mais nova, runs por dia (local e UTC),
  `adhoc_runs`, `warmup_runs`, `invalid_timestamps` (nulo, não numérico, ≤0 ou >1e12).
- `GET /benchmark/runs` ganhou `until` (junto de `since`).
- Frontend: painel Sessões com colunas Primeira run / Última run, paginado; cabeçalho (total de runs e
  último benchmark) vem do `history/summary`; "Atualizar" e o auto-refresh chamam `invalidate()` e refazem
  gráfico, sessões e runs (o botão manual também recarrega o preload de 5.000 runs).
  As colunas de média (tokens/latência/custo por sessão) foram removidas do painel porque eram calculadas
  sobre o preload truncado.

## Resultado medido (cópia do banco real, servidor do worktree, porta 8013)
- `history/summary`: total_runs=6.014, newest_run_at=01/10/2026 19:19:08, adhoc_runs=29, warmup_runs=3,
  invalid_timestamps=0.
- `/benchmark/sessions`: primeira linha = `adhoc`, runs=29, last_run_at=01/10/2026 19:19, 27 sessões no total.
- Screenshot: `docs/img/history-depois.png`.

## Testes
`tests/test_history.py` (sessão `adhoc` antiga + runs em 28/09, 30/09 e 01/10/2026 → aparece primeiro com
`last_run_at` correto; `/benchmark/runs` e `/timeseries` devolvem runs depois de 27/09; >5.000 runs; ms/ISO;
inválidos; duplicados; ordem; fuso local × UTC) e `scripts/check_frontend_charts.mjs` (lógica pura nova).

## Pendências / observações
- Sessões sem nenhuma run (sweeps, benchmarks abortados) continuam listadas, ordenadas por `created_at`.
- "Antes": não há screenshot do estado anterior (NÃO MEDIDO); o comportamento está descrito na tabela acima.
