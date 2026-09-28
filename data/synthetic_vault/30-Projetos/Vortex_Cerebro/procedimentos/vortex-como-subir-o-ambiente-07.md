---
id: 20261105-1657
title: Vortex — Subir o ambiente 07
area: Projetos
type: nota
tags: [vortex, procedimentos, subir]
status: ativo
created: 2026-11-05 16:57
updated: 2026-11-09 20:50
projeto: vortex
---

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check.

## Aberto

Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Proximos passos

The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Decisao

Cold start dominates the p95 numbers in every run so far. Cold start dominates the p95 numbers in every run so far.

## Contexto

Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[2026-03-31]] [[inbox-esboco-de-experimento-018]] [[parser-de-frontmatter-039]] [[reranker-local-043]]
