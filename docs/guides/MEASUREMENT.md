# MEASUREMENT — o que é medido, estimado e indisponível

Rótulos usados em todo o projeto: **medido** (vem do provedor ou de contagem exata), **estimado** (heurística local),
**indisponível** (não há dado; nunca preenchido com número inventado).

## Medido
| Grandeza | Origem |
|---|---|
| Tokens/custo do juiz JEV (`jev_input_tokens`, `jev_output_tokens`, `jev_cost`) | uso reportado pelo provedor (TypeSafe) |
| Latência de cada etapa | `perf_counter` local |
| `model_input_tokens` / `model_output_tokens` do consumidor | uso reportado pelo provedor/agente (modo `answer`) |
| Gasto de hoje/30 dias vs teto | soma de `runs` (somente valores medidos) — `app/services/costs.py` |
| Hit rate do cache JEV por candidato (`jev_cache_hits`) e do cache de resultado (só pipelines gratuitos) | contadores do próprio código |

## Estimado
| Grandeza | Como | Limite conhecido |
|---|---|---|
| `context_tokens`, `candidate_tokens_*`, `prompt_tokens_estimate` | `estimate_tokens`: `max(chars/4, palavras*1.3) * 1.13` | o fator 1.13 (`PT_CALIBRATION_FACTOR`) é o ponto médio de uma faixa documentada de 8–18%, **não** uma calibração nova |
| Economia vs "sem Gateway" | não medida (T2.2 pendente) | — |

### Razão empírica estimador × uso real (pend. 9)
`scripts/calibrate_token_estimate.py <cópia do benchmark.db>` compara, nas mesmas execuções, `model_input_tokens`
(provedor) com `prompt_tokens_estimate` (estimador), **apenas** consumidor `generic` (agentes completos somam system
prompt e schemas de ferramentas e são excluídos). Cópia de `benchmark.db` de 2026-10-07 (copiada para `$TMPDIR`,
aberta `mode=ro`):

- Consumidor `qwen3:8b` via ollama, n = 9 prompts: razão real/estimado **mediana 1,273; média 1,256; desvio 0,091;
  p10 1,244; p90 1,314** (mín 1,024; máx 1,324).
- Interpretação: **para o tokenizer do qwen3, o estimador atual (já com 1,13) subestima ~27%** (mediana). Isso
  sugere um fator total ≈ 1,13 × 1,27 ≈ 1,44 *para esse tokenizer*.
- **Não aplicado**: n=9 e um único tokenizer (qwen3, não o de Claude/GPT); o estimador é deliberadamente
  independente do modelo. Os prompts são todos em português do vault, portanto a razão mistura português + XML do
  contexto. Nada foi alterado no comportamento padrão.

## Indisponível / pendente
- **Calibração contra tokenizer real (T2.1)**: `tiktoken`, `transformers` e `tokenizers` **não estão instalados** no
  `.venv`. Não há como obter contagem de um tokenizer de Claude offline (só a API reporta). Por isso nenhum fator novo
  foi fixado no código. Caminho: instalar `tiktoken` (opcional) ou usar `usage.input_tokens` da API, gerar um JSON
  `{"pt": <fator>, "other": <fator>}` (fator relativo à heurística bruta, antes do 1,13) e apontar
  `ANAMNESIA_TOKEN_CALIBRATION` para ele. O gancho existe em `app/services/token_estimate.py`
  (`estimate_tokens(text, lang='auto')`); sem a variável, devolve **exatamente** o estimador atual.
- Tokens de agentes que não expõem uso (ex.: `claude_code` com `model_input_tokens = 0` em várias execuções):
  indisponível, não zero.
- **Taxa real de repetição de consultas** (pend. 3): ver abaixo.
- `consumer_tokens` com origem medido/estimado (T2.3) e experimento com/sem Gateway (T2.2): não implementados aqui.

## Hit rate de cache
`scripts/measure_cache_hit_rate.py [--queries 8] [--json out.json]` repete uma lista de perguntas duas vezes numa
cópia temporária do vault sintético, com **backend JEV stub** (sem rede, sem custo). Resultado medido (8 perguntas):

| passada | cache JEV por candidato | chamadas ao backend | cache de resultado (pipeline gratuito `auto`) |
|---|---|---|---|
| fria | 0/64 (0%) | 8 | 0/8 (0%) |
| quente | 64/64 (100%) | 0 | 8/8 (100%) |

**Isto mede a correção do mecanismo, não a taxa de repetição do mundo real**: a passada quente é 100% por
construção porque a mesma lista é repetida. A taxa real exige `runs.metrics_json` (`jev_cache_hits`,
`result_cache_hit`) acumulado em uso normal.

## Teto de orçamento (T6.4)
`app/gateway/budget_guard.py`, **desligado por padrão**. Com `ANAMNESIA_BUDGET_ENFORCE=1`:
- status = pior entre teto diário e mensal (mesmas janelas de `/api/costs/summary`: dia desde 00:00 local, mês = 30 dias);
- `exceeded` (gasto ≥ teto) e pipeline pago (`graphify_jev`, `graphify_jev_opt`) → plano vira `baseline`;
  métricas: `budget_degraded=true`, `budget_degraded_reason`, `budget_requested_pipeline`, `budget_status`;
- `warn` (≥ 80%) → só `budget_warning`; pipelines gratuitos nunca são alterados;
- falha ao ler o gasto nunca bloqueia a busca (`budget_status="unknown"`).
- Limite: o gasto só conta valores **medidos**; custo desconhecido não dispara o teto. O gasto de geração em
  `mode=answer` (fora do `search`) não é interceptado por este gancho, apenas a etapa de recuperação paga.
