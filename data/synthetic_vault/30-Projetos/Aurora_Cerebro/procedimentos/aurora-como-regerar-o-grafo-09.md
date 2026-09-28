---
id: 20260730-1631
title: Aurora — Regerar o grafo 09
area: Projetos
type: nota
tags: [aurora, procedimentos, regerar]
status: ativo
created: 2026-07-30 16:31
updated: 2026-09-13 20:09
projeto: aurora
---

## Implementacao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

## Como reproduzir

We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Alternativas

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[inbox-ideia-solta-sobre-busca-013]] [[2026-05-06]] [[kraken-conceitos-de-bm25-02]] [[reranker-local-063]]
