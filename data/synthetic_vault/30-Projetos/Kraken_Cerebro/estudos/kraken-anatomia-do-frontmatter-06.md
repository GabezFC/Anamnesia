---
id: 20261005-1750
title: Kraken — Anatomia do frontmatter 06
area: Projetos
type: estudo
tags: [kraken, estudos, anatomia]
status: ativo
created: 2026-10-05 17:50
updated: 2026-10-24 22:09
projeto: kraken
---

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. We prefer explicit failure over silent degradation in the answer path. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Implementacao

A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. Recall@5 is the primary metric; exact match is only a sanity check.

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[reranker-local-043]]
