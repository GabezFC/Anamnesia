---
id: 20260321-0914
title: Plano de viagem 28
area: Pessoal
type: nota
tags: [pessoal, plano]
status: ativo
created: 2026-03-21 09:14
updated: 2026-04-14 12:37
---

## Decisao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Referencias

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index.

## Contexto

Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Detalhes tecnicos

O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Latency budget is split between retrieval, rerank and composition.

## Riscos

Latency budget is split between retrieval, rerank and composition. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. A decisao foi tomada depois de comparar tres alternativas equivalentes. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[estudo-avaliacao-offline-021]] [[estudo-metricas-de-ranqueamento-034]]
