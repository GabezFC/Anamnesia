---
id: 20260920-0835
title: Kraken — Retrieval service 01
area: Projetos
type: nota
tags: [kraken, componentes, retrieval]
status: ativo
created: 2026-09-20 08:35
updated: 2026-10-10 12:18
projeto: kraken
---

## Contexto

Latency budget is split between retrieval, rerank and composition. The retrieval layer keeps a small LRU in front of the vector index. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Riscos

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca.

## Consequencias

O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[inbox-anotacao-de-podcast-021]] [[vortex-hnsw-na-pratica-09]] [[mapa-de-riscos-036]]
