# Onda 9 — experimentos de retrieval (ANA-225..237)

Gerado por `scripts/measure_onda9.py` (2026-10-12T23:17:19). Corpus `data/synthetic_vault`, golden `golden-v2`.
Veredito só no split **test** (23 itens respondíveis de 34); parâmetros escolhidos na calibração (87 respondíveis). Offline, 0 tokens pagos. Ollama: `{"running": false, "error": "URLError"}`.

> n pequeno: IC bootstrap largos; diferença pontual sem IC fora de zero **não** é resultado. Corpus sintético: não generaliza para o vault real sem remedir.

| Item | Veredito | Evidência (test) |
|---|---|---|
| ANA-226 | **ADOTAR** | correção de bug (peso do heading caía na coluna `file`), sem piora: sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.1%); default passou a section=2.0 (MG_EXP_BM25_SECTION_WEIGHT=1.0 restaura o ranking antigo) |
| ANA-227 max_candidates=100 | **MANTER_OPT_IN** | sem efeito no golden (nenhum item perde fonte no corte); garantia estrutural testada: sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%) |
| ANA-227 max_candidates=10 | **MANTER_OPT_IN** | sem efeito no golden (nenhum item perde fonte no corte); garantia estrutural testada: sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+66.3%) |
| ANA-228 | **MANTER_OPT_IN** | ganho pontual sem significância, n pequeno (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0217 IC[+0.0000,+0.0652]; Δtokens=-3.8%) |
| ANA-229 | **REJEITAR** | regressão pontual em mrr (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=-0.0217 IC[-0.0652,+0.0000]; Δtokens=-4.9%) |
| ANA-230 | **REJEITAR** | sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%) |
| ANA-231 | **REJEITAR** | sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%) |
| ANA-232 | **REJEITAR** | regressão pontual em mrr (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=-0.0217 IC[-0.1087,+0.0652]; Δtokens=-0.6%) |
| ANA-233 | **ADOTAR** | ≥10% menos tokens sem perda (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=-57.9%) |
| ANA-234 | **REJEITAR** | sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%); latência mediana PPR/BFS = 24.5x |
| ANA-235 | **BLOCKED** | canal semântico (RRF): precisa de modelo local Ollama; running=False, modelos=[]. Infra + testes com backend fake entregues; nada medido. |
| ANA-225 | **BLOCKED** | backend JEV local (concordância com o juiz pago): precisa de modelo local Ollama; running=False, modelos=[]. Infra + testes com backend fake entregues; nada medido. |
| ANA-236 | **ADOTAR** | ≥10% menos tokens sem perda (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0435 IC[+0.0000,+0.1087]; Δtokens=-33.3%) |
| ANA-237 budget=350 | **REJEITAR** | sem ganho mensurável (Δfact_in_ctx=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+5.6%) |
| ANA-237 budget=600 | **REJEITAR** | sem ganho mensurável (Δfact_in_ctx=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+5.8%) |
| ANA-237 budget=1000 | **REJEITAR** | sem ganho mensurável (Δfact_in_ctx=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%) |

## ANA-226
Escolha na calibração: `section_weight=2.0`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545 | 3.13 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 3.09 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **ADOTAR** — correção de bug (peso do heading caía na coluna `file`), sem piora: sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.1%); default passou a section=2.0 (MG_EXP_BM25_SECTION_WEIGHT=1.0 restaura o ranking antigo)

## ANA-227 max_candidates=100
Escolha na calibração: `scope_before_topn`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.978 [0.935, 1.000] | 510.4 | 1.7 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.978 [0.935, 1.000] | 510.4 | 1.68 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **MANTER_OPT_IN** — sem efeito no golden (nenhum item perde fonte no corte); garantia estrutural testada: sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%)

## ANA-227 max_candidates=10
Escolha na calibração: `scope_before_topn`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.978 [0.935, 1.000] | 307.0 | 1.14 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.978 [0.935, 1.000] | 510.4 | 1.56 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **MANTER_OPT_IN** — sem efeito no golden (nenhum item perde fonte no corte); garantia estrutural testada: sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+66.3%)

## ANA-228
Escolha na calibração: `unified_tokens`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 3.16 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.978 [0.935, 1.000] | 524.8 | 3.15 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **MANTER_OPT_IN** — ganho pontual sem significância, n pequeno (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0217 IC[+0.0000,+0.0652]; Δtokens=-3.8%)

## ANA-229
Escolha na calibração: `prefix>=4`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 1.9 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.935 [0.870, 1.000] | 518.7 | 3.66 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **REJEITAR** — regressão pontual em mrr (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=-0.0217 IC[-0.0652,+0.0000]; Δtokens=-4.9%)

## ANA-230
Escolha na calibração: `magnitude`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 2.55 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 35.73 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **REJEITAR** — sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%)

## ANA-231
Escolha na calibração: `complex_dedup_max=2`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 1142.3 | 3.35 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 1142.3 | 3.46 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **REJEITAR** — sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%)

## ANA-232
Escolha na calibração: `lex_rerank_top=20 alpha=0.5`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 327.7 | 3.03 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.935 [0.870, 1.000] | 325.7 | 7.76 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **REJEITAR** — regressão pontual em mrr (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=-0.0217 IC[-0.1087,+0.0652]; Δtokens=-0.6%)

## ANA-233
Escolha na calibração: `{'ambiguous': 0.8, 'factual': 0.7, 'long': 0.8, 'multi_hop': 0.2, 'navigation': 0.8, 'paraphrased': 0.8, 'rare_terms': 0.8, 'short': 0.8, 'technical': 0.8}`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 1142.3 | 3.32 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 480.5 | 3.07 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **ADOTAR** — ≥10% menos tokens sem perda (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=-57.9%)

## ANA-234
Escolha na calibração: `—`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 1147.3 | 3.2 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 1147.5 | 78.27 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **REJEITAR** — sem ganho mensurável (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%); latência mediana PPR/BFS = 24.5x

## ANA-235
canal semântico (RRF): precisa de modelo local Ollama; running=False, modelos=[]. Infra + testes com backend fake entregues; nada medido.

## ANA-225
backend JEV local (concordância com o juiz pago): precisa de modelo local Ollama; running=False, modelos=[]. Infra + testes com backend fake entregues; nada medido.

## ANA-236
Escolha na calibração: `rewrite+unified`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 3.09 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 1.000 [1.000, 1.000] | 363.9 | 1.91 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **ADOTAR** — ≥10% menos tokens sem perda (Δrecall=+0.0000 IC[+0.0000,+0.0000]; Δmrr=+0.0435 IC[+0.0000,+0.1087]; Δtokens=-33.3%)

## ANA-237 budget=350
Escolha na calibração: `budget_fit`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 270.6 | 3.11 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 285.7 | 3.23 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 57 → 52

Veredito: **REJEITAR** — sem ganho mensurável (Δfact_in_ctx=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+5.6%)

## ANA-237 budget=600
Escolha na calibração: `budget_fit`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 500.1 | 3.15 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 529.1 | 3.11 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 9 → 1

Veredito: **REJEITAR** — sem ganho mensurável (Δfact_in_ctx=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+5.8%)

## ANA-237 budget=1000
Escolha na calibração: `budget_fit`

| braço | hit@k (Wilson) | recall (boot) | MRR (boot) | tokens ctx | lat mediana ms |
|---|---|---|---|---|---|
| control | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 3.38 |
| arm | 0.826 [0.629, 0.930] | 0.913 [0.826, 0.978] | 0.957 [0.891, 1.000] | 545.4 | 3.6 |

fact_in_context: control 1.000 [1.000, 1.000] → arm 1.000 [1.000, 1.000]; blocos descartados por orçamento: 0 → 0

Veredito: **REJEITAR** — sem ganho mensurável (Δfact_in_ctx=+0.0000 IC[+0.0000,+0.0000]; Δtokens=+0.0%)

## Regra de default
Só ANA-226 (correção de bug) mudou um default. Todo ADOTAR/MANTER_OPT_IN dos demais itens permanece com a flag **OFF**: o corpus é sintético, o test tem poucos itens e os ADOTAR por economia de tokens (ANA-233, ANA-236) devem ser remedidos no vault real antes de ligar.

## Não medido
- ANA-225/235 e o reranker neural (ANA-232): dependem de Ollama com modelo; ver BLOCKED acima.
- Vault real: não usado (read-only, sem golden rotulado).

