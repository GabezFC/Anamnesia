# Livro de custos por chamada (`/api/costs/*`)

Cada linha de `runs` é uma chamada. Colunas aditivas (migração `ALTER TABLE`, idempotente):
`project` (do escopo da busca: `projeto:x` → `x`; global/área → `NULL`), `terminal_session_id`
(env `MG_TERMINAL_SESSION`, senão `NULL`), `cost_origin` (`measured|estimated|unavailable`).
Preenchidas em `Database.save_run` quando o chamador não as informa; linhas antigas ficam `NULL`.
Índices: `runs(project, created_at)` e `runs(created_at)`. Tabela nova `budgets(period, ceiling_usd, updated_at)`.

## Rótulos de origem
Cada número do resumo/chamada é `{"value": x, "origin": ...}`:
- `measured`: tokens/custo do JEV (uso devolvido pela API), latência, cache.
- `estimated`: tokens de candidatos e de contexto (estimador), economia/redução.
- `unavailable`: valor `null` (ex.: JEV sem uso reportado).
- Total é `measured` só se todas as parcelas forem; uma estimada rebaixa o total.
- Dinheiro: só quando o preço do modelo é verificado (`config.pricing.price_status`); senão `null`.
  Pipelines sem chamada de API contam `0.0` (medido). Sem chamadas com preço → `cost_usd.value = null`.

## Rotas
| Rota | Notas |
| --- | --- |
| `GET /summary?range=today\|7d\|30d\|all&project=` | cartões, série por dia, `budget.day/month` |
| `GET /calls?cursor=&limit=&project=` | paginação keyset `(created_at, run_id)`; `next_cursor` |
| `GET /calls/{run_id}` | detalhe + `sources`, `candidates` (KEEP/REVIEW/DROP/QUARANTINE), métricas |
| `GET /export.csv?range=&project=` | colunas com `*_origin` |
| `PUT /budget` `{period: day\|month, ceiling_usd}` | exige `require_local_write`; `null` remove o teto |
| `GET /stream?max_seconds=&max_events=&poll_interval=&after_rowid=` | SSE `event: call`, sonda o DB; termina com `event: end` |

`MG_METRICS_ONLY=1`: calls, detalhe, CSV e stream omitem `query`, `context`, `answer`.

## Teto (G5)
`budget_status(gasto, teto)`: `ok` < 80%, `warn` ≥ 80%, `exceeded` ≥ 100%. Gasto desconhecido ou sem teto → `ok`.
Dia = desde 00:00 local; mês = últimos 30 dias. **Ainda não altera a recuperação** (degradar para baseline é etapa futura).

## Pendências
- O router não está registrado no app: `app.include_router(app.api.costs.router)` (orquestrador).
- `get_db` usa `routes.gw().db`; testes sobrescrevem a dependência.
