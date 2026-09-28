---
id: 20260419-1337
title: Retry com backoff 07
area: Dev-IA
type: nota
tags: [dev, ia, retry]
status: ativo
created: 2026-04-19 13:37
updated: 2026-05-20 15:26
---

## Aberto

Em teste local o ganho apareceu principalmente nas consultas curtas. This is a documentation note, not a runbook; keep the steps elsewhere. A decisao foi tomada depois de comparar tres alternativas equivalentes. Em teste local o ganho apareceu principalmente nas consultas curtas.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Riscos

Cold start dominates the p95 numbers in every run so far. Registro importante: o servico interno responde na porta 49106 dentro da rede docker. A ideia central e reduzir o custo de contexto sem perder recall. A ideia central e reduzir o custo de contexto sem perder recall.

## Proximos passos

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check.

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca.

## Como reproduzir

Recall@5 is the primary metric; exact match is only a sanity check. O comportamento so aparece quando o cache esta frio.

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[chunking-hibrido-031]] [[parser-de-frontmatter-059]] [[vortex-decisao-driver-do-banco-07]] [[sanitizacao-de-markdown-078]]
