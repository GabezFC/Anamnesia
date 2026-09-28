---
id: 20260128-1710
title: Estudo: Grafos de conhecimento 26
area: Estudos
type: estudo
tags: [estudo, grafos]
status: ativo
created: 2026-01-28 17:10
updated: 2026-02-27 17:13
---

## Resumo

Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Consequencias

Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio.

## Alternativas

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

## Proximos passos

O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[kraken-limites-de-contexto-06]] [[aurora-limites-de-contexto-06]]
