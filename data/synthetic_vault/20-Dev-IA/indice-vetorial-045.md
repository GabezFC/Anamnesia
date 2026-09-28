---
id: 20260527-1703
title: Indice vetorial 45
area: Dev-IA
type: nota
tags: [dev, ia, indice]
status: ativo
created: 2026-05-27 17:03
updated: 2026-06-05 18:40
---

## Riscos

Latency budget is split between retrieval, rerank and composition. We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Contexto

A ideia central e reduzir o custo de contexto sem perder recall. Registro importante: o servico interno responde na porta 49043 dentro da rede docker. O comportamento so aparece quando o cache esta frio.

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Implementacao

A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar.

## Alternativas

Vale revisitar isso quando o volume de notas dobrar. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[quantizacao-gguf-076]] [[kraken-decisao-estrategia-de-cache-09]]
