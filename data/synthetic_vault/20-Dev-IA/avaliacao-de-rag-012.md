---
id: 20260424-1642
title: Avaliacao de rag 12
area: Dev-IA
type: nota
tags: [dev, ia, avaliacao]
status: ativo
created: 2026-04-24 16:42
updated: 2026-05-20 18:19
---

## Implementacao

This is a documentation note, not a runbook; keep the steps elsewhere. Recall@5 is the primary metric; exact match is only a sanity check.

## Consequencias

Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check.

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[planejamento-trimestral-040]] [[plano-de-viagem-020]] [[handoff-do-time-015]]
