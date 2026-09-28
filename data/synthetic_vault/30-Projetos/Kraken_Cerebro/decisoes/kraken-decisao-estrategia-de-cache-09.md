---
id: 20260908-1111
title: Kraken — Estrategia de cache 09
area: Projetos
type: decisao
tags: [kraken, decisoes, estrategia]
status: ativo
created: 2026-09-08 11:11
updated: 2026-09-29 13:33
projeto: kraken
---

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall.

## Como reproduzir

Latency budget is split between retrieval, rerank and composition. Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Decisao

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

## Contexto

Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[estudo-estatistica-bayesiana-006]] [[contrato-do-fornecedor-043]]
