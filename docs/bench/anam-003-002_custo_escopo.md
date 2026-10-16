# ANAM-003 / ANAM-002 — custo e escopo

Sem mudança em retrieval/ranking/JEV: baseline de recuperação não se aplica. Medição relevante = **custo 0 inalterado**.

| Verificação | Resultado |
|---|---|
| Provider local (ollama/vllm) com tetos `RUN=0`/`DAY=0` e 10^6 tokens | 5 chamadas, 0 bloqueios, gasto 0.0 (`test_local_cost_zero_unchanged`) |
| 50 tentativas pagas com teto run 0.02 USD | gasto acumulado <= 0.02; chamadas reais < 50 (`test_run_cap_never_exceeded_over_many_attempts`) |
| Teto diário compartilhado entre runs | soma dos runs == ledger diário <= teto |
| Modelo pago sem preço | limitado por preço pessimista (nunca tratado como grátis) |
| Loop de resposta, tetos padrão | comportamento idêntico (m1 falha -> m2 responde) |
| REST sem sessão/credencial pedindo `scope` | 403 (antes: escopo arbitrário aceito) |

Env novas: `ANAMNESIA_BUDGET_RUN_USD` (0.05), `ANAMNESIA_BUDGET_DAY_USD` (1.00), `ANAMNESIA_PRICING_FILE`,
`ANAMNESIA_PRICE_UNKNOWN_IN`/`_OUT` (15/75 USD/Mtok), `ANAMNESIA_SCOPE_ANON` (deny|ignore|allow).
Mudadas: `ANAMNESIA_BUDGET_ENFORCE` default ON; `ANAMNESIA_PAID_CALLS` exige `1|true|yes|on` (antes: ligado se não for 0).
