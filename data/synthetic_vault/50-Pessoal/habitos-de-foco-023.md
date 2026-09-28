---
id: 20260316-1609
title: Habitos de foco 23
area: Pessoal
type: nota
tags: [pessoal, habitos]
status: ativo
created: 2026-03-16 16:09
updated: 2026-03-27 00:22
---

## Detalhes tecnicos

The retrieval layer keeps a small LRU in front of the vector index. A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Contexto

A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[aurora-conceitos-de-bm25-08]] [[aurora-decisao-modelo-local-padrao-06]] [[estudo-arquitetura-de-transformers-044]]
