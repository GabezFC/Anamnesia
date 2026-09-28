---
id: 20260618-1037
title: Retry com backoff 67
area: Dev-IA
type: nota
tags: [dev, ia, retry]
status: ativo
created: 2026-06-18 10:37
updated: 2026-07-04 12:21
---

## Consequencias

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Alternativas

Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Vale revisitar isso quando o volume de notas dobrar.

## Detalhes tecnicos

This is a documentation note, not a runbook; keep the steps elsewhere. Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[inbox-anotacao-de-podcast-009]]
