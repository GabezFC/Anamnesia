# Benchmark de Model Routing — 2026-10-07

> **SIMULATED (stub runner): numbers are NOT evidence**
>
> Runner determinístico (stub). Nada abaixo mede modelos reais; as respostas às 12 perguntas ficam 'sem dados'.

## Configuração
- tarefas: 20 · estratégias: STATIC_CHEAP, STATIC_DEFAULT, STATIC_STRONG, DYNAMIC_ROUTER, ORACLE · políticas: balanced
- modelos: ollama-qwen-coder(tier 1, preço local_zero), ollama-llama(tier 1, preço local_zero), vllm-local(tier 1, preço local_zero), openai-small(tier 1, preço unavailable), openai-mid(tier 2, preço unavailable), anthropic-haiku(tier 1, preço unavailable), anthropic-sonnet(tier 2, preço unavailable), anthropic-opus(tier 3, preço unavailable), openrouter-llama(tier 2, preço unavailable), hf-inference(tier 2, preço unavailable), nvidia-hosted(tier 2, preço unavailable)
- baselines escolhidos: {"STATIC_CHEAP": "ollama-llama", "STATIC_DEFAULT": "anthropic-sonnet", "STATIC_STRONG": "anthropic-opus"}
- execuções de modelo: 220 · acertos de cache: 87 (cada tarefa×modelo roda 1×)
- registry_version: `bench-cf77ca3a5bd8`


## As 12 perguntas (§65) — só com dados

1. **O Dynamic Router economizou tokens?** sem dados
2. **O Dynamic Router economizou dinheiro?** sem dados
3. **Quanto custou o próprio router?** sem dados
4. **Quanto custou a verificação?** sem dados
5. **Quantas tarefas precisaram de escalation?** sem dados
6. **Quantas tarefas foram over-routed?** sem dados
7. **Quantas foram under-routed?** sem dados
8. **O custo por tarefa resolvida melhorou?** sem dados
9. **A qualidade mudou?** sem dados
10. **Em quais categorias o routing funciona melhor?** sem dados
11. **Em quais categorias ele piora?** sem dados
12. **Qual política/threshold apresentou melhor resultado?** sem dados

## Mecânica (SIMULADA — não é evidência)

_SIMULATED (stub runner): numbers are NOT evidence_

| Estratégia | N | resolvidas | taxa | custo total | custo/resolvida | tokens/resolvida | escalation |
|---|---|---|---|---|---|---|---|
| DYNAMIC_ROUTER | 20 | 18 | 0.9 (simulado) | sem dados | sem dados | 66.611111 (simulado) | 0.35 (simulado) |
| ORACLE | 20 | 20 | 1.0 (simulado) | sem dados | sem dados | 44.5 (simulado) | 0.0 (simulado) |
| STATIC_CHEAP | 20 | 8 | 0.4 (simulado) | 0.0 USD (simulado) | 0.0 USD (simulado) | 107.375 (simulado) | 0.0 (simulado) |
| STATIC_DEFAULT | 20 | 13 | 0.65 (simulado) | sem dados | sem dados | 67.615385 (simulado) | 0.0 (simulado) |
| STATIC_STRONG | 20 | 18 | 0.9 (simulado) | sem dados | sem dados | 48.555556 (simulado) | 0.0 (simulado) |

## Limitações

- Verificação do router usa o mesmo verificador objetivo do avaliador (tem acesso ao ground truth): escalonamento é mais preciso que um LIGHT real.
- memory_qa exige contexto recuperado, não injetado por este harness: execuções `--real` usam só tarefas autocontidas (extraction).
- Preço de nuvem ausente no registry ⇒ custo `null` (nunca 0); modelos locais custam 0 de token (não inclui energia/GPU).
- retry na mesma tarefa/modelo não é executado (retry_count=0 por construção); só escalonamento.
