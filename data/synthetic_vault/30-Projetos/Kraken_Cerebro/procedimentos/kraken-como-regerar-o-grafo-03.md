---
id: 20260912-1339
title: Kraken — Regerar o grafo 03
area: Projetos
type: nota
tags: [kraken, procedimentos, regerar]
status: ativo
created: 2026-09-12 13:39
updated: 2026-10-07 19:26
projeto: kraken
---

## Aberto

This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall.

## Contexto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Notes

Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Riscos

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[kraken-decisao-modelo-local-padrao-06]] [[kraken-como-girar-credenciais-06]]
