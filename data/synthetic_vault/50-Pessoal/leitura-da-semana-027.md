---
id: 20260320-0837
title: Leitura da semana 27
area: Pessoal
type: nota
tags: [pessoal, leitura]
status: arquivado
created: 2026-03-20 08:37
updated: 2026-05-02 16:21
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Alternativas

Latency budget is split between retrieval, rerank and composition. This is a documentation note, not a runbook; keep the steps elsewhere. O comportamento so aparece quando o cache esta frio.

## Medicoes

Latency budget is split between retrieval, rerank and composition. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. Recall@5 is the primary metric; exact match is only a sanity check.

## Aberto

The retrieval layer keeps a small LRU in front of the vector index. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[aurora-modulo-de-ranqueamento-05]] [[aurora-conceitos-de-bm25-02]] [[retrospectiva-da-sprint-005]] [[vortex-como-regerar-o-grafo-09]]
