---
id: 20260617-1000
title: Fila de jobs 66
area: Dev-IA
type: decisao
tags: [dev, ia, fila]
status: ativo
created: 2026-06-17 10:00
updated: 2026-07-07 17:58
---

## Decisao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. We prefer explicit failure over silent degradation in the answer path. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Notes

Deduplication happens before rerank, otherwise near-duplicates flood the top. Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

## Riscos

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[2026-05-09]] [[chunking-hibrido-011]] [[vortex-como-publicar-release-04]] [[kraken-decisao-biblioteca-de-embeddings-04]]
