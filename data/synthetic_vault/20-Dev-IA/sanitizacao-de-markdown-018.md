---
id: 20260430-1024
title: Sanitizacao de markdown 18
area: Dev-IA
type: nota
tags: [dev, ia, sanitizacao]
status: ativo
created: 2026-04-30 10:24
updated: 2026-06-10 15:54
---

## Riscos

O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check.

## Decisao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall.

## Proximos passos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas. This is a documentation note, not a runbook; keep the steps elsewhere.

## Detalhes tecnicos

We prefer explicit failure over silent degradation in the answer path. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[aurora-graph-loader-03]] [[batch-de-inferencia-035]] [[planejamento-trimestral-040]]
