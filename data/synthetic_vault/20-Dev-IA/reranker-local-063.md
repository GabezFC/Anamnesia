---
id: 20260614-1809
title: Reranker local 63
area: Dev-IA
type: nota
tags: [dev, ia, reranker]
status: ativo
created: 2026-06-14 18:09
updated: 2026-06-19 21:43
---

## Decisao

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Medicoes

Em teste local o ganho apareceu principalmente nas consultas curtas. Recall@5 is the primary metric; exact match is only a sanity check.

## Detalhes tecnicos

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path.

## Notes

Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Contexto

Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[politica-de-dados-059]] [[relatorio-para-stakeholders-021]]
