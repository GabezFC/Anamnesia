# Orquestração de subagentes (Fase 11, backend)

Spec: `Anamnesia/arquitetura/anamnesia-orquestracao-de-subagentes.md`. Esta fase entrega o backend; o lançamento em
sessões de terminal reais e a UI vêm depois.

## Peças
| Arquivo | Papel |
| --- | --- |
| `config/orchestration.yaml` | classes `cheap/medium/strong` (faixas de rank, **não** ids de modelo), predefinições `economic/balanced/max`, limites |
| `app/orchestration/config.py` | carregador + validação (parser YAML-subset de `app/routing/registry.py`, sem PyYAML) |
| `app/orchestration/roles.py` | contratos: pesquisador e revisor **somente leitura** (revisor roda testes); implementador só escreve dentro do `cwd` |
| `app/orchestration/runs.py` | `.anamnesia/runs/<run_id>/` (`task.md`, `events.jsonl`, `summary.json`, `<step>/result.md`, `<step>/status.json`); `safe_join` rejeita `..`, absolutos e symlinks que escapam; máquina de estados `planned→running→done｜failed｜cancelled` |
| `app/orchestration/launchers.py` | `SessionLauncher` (Protocol), `FakeLauncher` (testes), `InProcessModelLauncher` (chama o adapter direto, sem terminal) |
| `app/orchestration/orchestrator.py` | `Orchestrator.plan / submit / run / wait / get / list / cancel` |
| `app/api/orchestration.py` | router `/api/orchestration` (o orquestrador do app ainda precisa incluí-lo em `app/main.py`) |
| `scripts/orchestration_experiment.py` | experimento da seção 5 |

## Classes → tiers do registry
Cada classe cobre uma faixa da posição relativa do tier (`índice/(n-1)`): cheap 0–0.33, medium 0.34–0.66, strong 0.67–1.
3 tiers → `{cheap:[1], medium:[2], strong:[3]}`; 5 tiers → `{cheap:[1,2], medium:[3], strong:[4,5]}`. Classe sem modelo
utilizável cai para a classe acima e gera aviso em `summary.json.warnings`. O modelo dentro da classe é escolhido por
`app.routing.router.route` com a política do preset.

## Plano (v1, determinístico, sem LLM)
`researcher → implementer → reviewer`, com o texto da tarefa repassado. Tarefa com ≥2 itens de lista gera um pesquisador
por item (até 8), em paralelo (teto `max_parallel_subagents`, padrão 3); implementador e revisor esperam as dependências.
O resultado de cada etapa entra (truncado) no prompt da seguinte.

## Contrato com o lançador
Variáveis de ambiente por etapa: `ANAMNESIA_RUN_DIR`, `ANAMNESIA_STEP`, `ANAMNESIA_STEP_DIR`, `ANAMNESIA_ROLE`,
`ANAMNESIA_MODEL_ID`, `ANAMNESIA_MODEL`, `ANAMNESIA_PROVIDER`, `ANAMNESIA_READ_ONLY`. O subagente escreve
`<step_dir>/result.md` e `<step_dir>/status.json` (`ok`, `error`, `input_tokens`, `output_tokens`, `latency_ms`; tokens
não reportados = `null`). Para ligar ao Terminal Manager basta implementar `launch/send/close/is_alive`.

## Custo, escalonamento, tetos
- Custo por etapa **só** com `price_status == verified` e tokens reportados; modelos locais = 0.0 (`local_zero`);
  caso contrário `cost_usd: null`, `cost_status: "unavailable"`. Totais: `measured | partial | unavailable`.
- Duas falhas seguidas na mesma etapa → escala **uma** classe, **uma** vez (`escalation.next_model`); evento `escalated`.
  Esgotado → run `failed`.
- `budget_usd` (config ou por run): com teto, etapas rodam em série; run vai a `failed` (`budget_exceeded` /
  `budget_exhausted`) se o gasto passar do teto ou se a próxima chamada, estimada pela maior tentativa já vista,
  não couber. Sem preço verificado o teto não é aplicável → `failed: budget_unenforceable_*` antes de gastar.
  Limitação: a primeira chamada não tem histórico, então o teto só é checado após ela.
- `cancel`: `planned` → cancelado na hora; `running` → sinaliza, fecha as sessões, estado final `cancelled`.

## API
| Método | Rota | Notas |
| --- | --- | --- |
| GET | `/api/orchestration/presets` | predefinições, mapeamento classe→tier atual, limites |
| GET | `/api/orchestration/runs?path=` | runs em memória + em disco do projeto |
| POST | `/api/orchestration/runs` | `require_local_write` (token + loopback); corpo `{path, task, preset, project_id?, budget_usd?}`; 202 |
| GET | `/api/orchestration/runs/{id}?path=` | resumo + últimos 200 eventos |
| POST | `/api/orchestration/runs/{id}/cancel?path=` | `require_local_write` |

Hook para `memory_search mode='delegate'`: `Orchestrator.submit(task, preset, project_path) -> run_id`.

## Experimento (seção 5)
`python scripts/orchestration_experiment.py [--reps 3] [--task ...]` roda 3 predefinições × N repetições com launcher
**stub** (tokens sintéticos, rotulado) e imprime tokens/custo por papel (`measured`/`unavailable`). `--real` só chama
modelos se houver ao menos um utilizável; senão recusa (exit 2). O rótulo "mais barata" nunca sai sem custo menor **e**
mesmo número de testes passando (`--tests-passed economic=N balanced=N`); o script não roda testes.
