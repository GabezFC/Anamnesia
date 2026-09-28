---
id: 20260623-1342
title: Avaliacao de rag 72
area: Dev-IA
type: nota
tags: [dev, ia, avaliacao]
status: arquivado
created: 2026-06-23 13:42
updated: 2026-08-03 16:15
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Decisao

Cold start dominates the p95 numbers in every run so far. A ideia central e reduzir o custo de contexto sem perder recall.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Como reproduzir

The retrieval layer keeps a small LRU in front of the vector index. Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O comportamento so aparece quando o cache esta frio.

## Contexto

Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Referencias

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[vortex-decisao-biblioteca-de-embeddings-10]] [[kraken-licencas-das-dependencias-01]]
