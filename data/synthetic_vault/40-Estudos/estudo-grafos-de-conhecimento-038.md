---
id: 20260209-1434
title: Estudo: Grafos de conhecimento 38
area: Estudos
type: estudo
tags: [estudo, grafos]
status: ativo
created: 2026-02-09 14:34
updated: 2026-03-06 20:44
---

## Contexto

Latency budget is split between retrieval, rerank and composition. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o servico interno responde na porta 49092 dentro da rede docker. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Detalhes tecnicos

Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[vortex-conceitos-de-bm25-08]] [[kraken-retrieval-service-01]] [[roteador-de-modelos-069]]
