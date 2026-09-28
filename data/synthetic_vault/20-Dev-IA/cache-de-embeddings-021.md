---
id: 20260503-1215
title: Cache de embeddings 21
area: Dev-IA
type: decisao
tags: [dev, ia, cache]
status: ativo
created: 2026-05-03 12:15
updated: 2026-05-24 19:04
---

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Medicoes

We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[observabilidade-de-agentes-068]] [[inbox-rascunho-de-api-008]] [[auditoria-de-acessos-046]] [[plano-de-viagem-028]]
