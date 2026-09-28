---
id: 20260127-1633
title: Estudo: Information retrieval 25
area: Estudos
type: estudo
tags: [estudo, information]
status: ativo
created: 2026-01-27 16:33
updated: 2026-03-04 19:47
---

## Riscos

The retrieval layer keeps a small LRU in front of the vector index. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: o driver escolhido foi asyncpg 0.38.2 por causa da licenca Apache-2.0. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Proximos passos

A decisao foi tomada depois de comparar tres alternativas equivalentes. O comportamento so aparece quando o cache esta frio. Latency budget is split between retrieval, rerank and composition. Vale revisitar isso quando o volume de notas dobrar.

## Detalhes tecnicos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[kraken-decisao-formato-do-indice-02]]
