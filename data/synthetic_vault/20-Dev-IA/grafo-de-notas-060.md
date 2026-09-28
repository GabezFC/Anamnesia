---
id: 20260611-1618
title: Grafo de notas 60
area: Dev-IA
type: nota
tags: [dev, ia, grafo]
status: arquivado
created: 2026-06-11 16:18
updated: 2026-07-17 18:24
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Decisao

We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far.

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index.

## Riscos

A causa raiz estava na normalizacao dos acentos antes da busca. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[estudo-engenharia-de-prompts-019]] [[2026-05-21]] [[2026-05-27]] [[kraken-anatomia-do-frontmatter-06]]
