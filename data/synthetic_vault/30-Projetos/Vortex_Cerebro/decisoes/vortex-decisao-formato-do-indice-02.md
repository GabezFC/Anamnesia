---
id: 20261021-1742
title: Vortex — Formato do indice 02
area: Projetos
type: decisao
tags: [vortex, decisoes, formato]
status: ativo
created: 2026-10-21 17:42
updated: 2026-11-19 21:28
projeto: vortex
---

## Contexto

Em teste local o ganho apareceu principalmente nas consultas curtas. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Implementacao

Latency budget is split between retrieval, rerank and composition. Registro importante: ficou definido um timeout de 206ms no QuaxilProxy antes de cair para o fallback textual. A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[2026-03-28]] [[sharding-do-indice-017]] [[kraken-graph-loader-09]]
