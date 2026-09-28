---
id: 20260122-0958
title: Inbox: Rascunho de api 20
area: Inbox
type: nota
tags: [rascunho, inbox, triagem]
status: inbox
created: 2026-01-22 09:58
updated: 2026-01-24 15:36
---

## Decisao

Em teste local o ganho apareceu principalmente nas consultas curtas. Vale revisitar isso quando o volume de notas dobrar. Recall@5 is the primary metric; exact match is only a sanity check. We prefer explicit failure over silent degradation in the answer path.

## Como reproduzir

A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Consequencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall.

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[2026-04-03]]
