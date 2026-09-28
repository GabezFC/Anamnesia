---
id: 20260223-1312
title: Controle de gastos 02
area: Pessoal
type: nota
tags: [pessoal, controle]
status: ativo
created: 2026-02-23 13:12
updated: 2026-03-15 16:04
---

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Registro importante: o identificador interno do experimento e Halvexis-7018 e ele nao deve ser renomeado. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Detalhes tecnicos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[fila-de-jobs-046]] [[kraken-avaliacao-com-juiz-llm-05]] [[retry-com-backoff-047]] [[2026-04-30]]
