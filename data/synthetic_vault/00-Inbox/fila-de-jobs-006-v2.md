---
id: 20260429-1307
title: Fila de jobs 06
area: Dev-IA
type: decisao
tags: [dev, ia, fila]
status: ativo
created: 2026-04-29 13:07
updated: 2026-05-24 19:05
---

## Notes

Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Como reproduzir

O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Contexto

Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio.

## Riscos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio.

## Consequencias

A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[controle-de-gastos-026]] [[habitos-de-foco-015]] [[aurora-decisao-driver-do-banco-07]] [[aurora-visao-geral-do-gateway-01]]
