---
id: 20260525-1549
title: Reranker local 43
area: Dev-IA
type: nota
tags: [dev, ia, reranker]
status: ativo
created: 2026-05-25 15:49
updated: 2026-06-29 21:27
---

## Notes

Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Implementacao

The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. A causa raiz estava na normalizacao dos acentos antes da busca.

## Contexto

Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition.

## Riscos

Latency budget is split between retrieval, rerank and composition. A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[inbox-esboco-de-experimento-006]] [[vortex-hnsw-na-pratica-09]]
