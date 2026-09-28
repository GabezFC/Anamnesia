---
id: 20260124-1112
title: Inbox: Recorte de artigo 22
area: Inbox
type: nota
tags: [recorte, inbox, triagem]
status: inbox
created: 2026-01-24 11:12
updated: 2026-01-30 14:26
---

## Resumo

A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition.

## Proximos passos

O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Recall@5 is the primary metric; exact match is only a sanity check. This is a documentation note, not a runbook; keep the steps elsewhere. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

Recall@5 is the primary metric; exact match is only a sanity check. Latency budget is split between retrieval, rerank and composition. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Implementacao

This is a documentation note, not a runbook; keep the steps elsewhere. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[estudo-grafos-de-conhecimento-038]]
