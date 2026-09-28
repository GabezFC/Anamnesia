---
id: 20260105-1259
title: Estudo: Algebra linear aplicada 03
area: Estudos
type: estudo
tags: [estudo, algebra]
status: ativo
created: 2026-01-05 12:59
updated: 2026-01-20 20:09
---

## Contexto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca. Latency budget is split between retrieval, rerank and composition.

## Decisao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Riscos

Latency budget is split between retrieval, rerank and composition. O comportamento so aparece quando o cache esta frio.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[kraken-decisao-biblioteca-de-embeddings-04]] [[onboarding-do-time-032]]
