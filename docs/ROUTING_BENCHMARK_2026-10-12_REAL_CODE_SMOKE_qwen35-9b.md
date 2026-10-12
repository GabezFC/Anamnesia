# Benchmark de Model Routing — 2026-10-12

> Execução REAL com modelos locais/configurados (temperatura 0). Amostra pequena: indicativa, não conclusiva.

## Configuração
- tarefas: 23 · estratégias: STATIC_CHEAP · políticas: balanced
- modelos: ollama-qwen35-9b(tier 1, preço local_zero)
- baselines escolhidos: {"STATIC_CHEAP": "ollama-qwen35-9b", "STATIC_DEFAULT": "ollama-qwen35-9b", "STATIC_STRONG": "ollama-qwen35-9b"}
- execuções de modelo: 23 · acertos de cache: 0 (cada tarefa×modelo roda 1×)
- registry_version: `bench-d384da895509`

- --real: 23 de 23 tarefas autocontidas (extraction); memory_qa excluída (use --with-memory)
- poder: N=23 por braço; poder estimado=0.0994 para detectar 10% (taxa-base 50%); necessário ~388 por braço
- **SUBDIMENSIONADO**: N=23 < 388; diferenças pequenas não são detectáveis

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

## Resultados por estratégia (não simulados)

| Estratégia | N | resolvidas | taxa | IC 95% (Wilson) | custo total | custo/resolvida | tokens/resolvida | escalation |
|---|---|---|---|---|---|---|---|---|
| STATIC_CHEAP | 23 | 23 | 1.0 (medido) | [0.857; 1.000] | 0.0 USD (medido) | 0.0 USD (medido) | 144.391304 (medido) | 0.0 (medido) |

## Limitações

- Verificação do router usa o mesmo verificador objetivo do avaliador (tem acesso ao ground truth): escalonamento é mais preciso que um LIGHT real.
- memory_qa exige contexto recuperado: só roda `--real` com `--with-memory` (contexto do gateway, igual para todos os modelos).
- Preço de nuvem ausente no registry ⇒ custo `null` (nunca 0); modelos locais custam 0 de token (não inclui energia/GPU).
- retry na mesma tarefa/modelo não é executado (retry_count=0 por construção); só escalonamento.
