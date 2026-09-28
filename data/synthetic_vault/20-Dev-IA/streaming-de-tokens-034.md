---
id: 20260516-1016
title: Streaming de tokens 34
area: Dev-IA
type: nota
tags: [dev, ia, streaming]
status: ativo
created: 2026-05-16 10:16
updated: 2026-05-31 11:41
---

## Riscos

The retrieval layer keeps a small LRU in front of the vector index. Deduplication happens before rerank, otherwise near-duplicates flood the top. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[revisao-de-escopo-038]] [[quantizacao-gguf-076]]
