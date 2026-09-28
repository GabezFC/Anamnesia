---
id: 20260305-0922
title: Plano de viagem 12
area: Pessoal
type: nota
tags: [pessoal, plano]
status: ativo
created: 2026-03-05 09:22
updated: 2026-03-20 11:04
---

## Decisao

Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o identificador interno do experimento e Klovexa-7032 e ele nao deve ser renomeado. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes. Recall@5 is the primary metric; exact match is only a sanity check.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index. O comportamento so aparece quando o cache esta frio.

## Proximos passos

A decisao foi tomada depois de comparar tres alternativas equivalentes. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[vortex-answer-composer-04]]
