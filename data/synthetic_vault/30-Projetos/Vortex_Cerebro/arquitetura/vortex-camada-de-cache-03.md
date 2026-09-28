---
id: 20261012-1209
title: Vortex — Camada de cache 03
area: Projetos
type: nota
tags: [vortex, arquitetura, camada]
status: ativo
created: 2026-10-12 12:09
updated: 2026-11-05 17:55
projeto: vortex
---

## Medicoes

A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere.

## Notes

The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. Registro importante: o servico interno responde na porta 49113 dentro da rede docker. A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[vortex-anatomia-do-frontmatter-06]] [[kraken-visao-geral-do-gateway-01]] [[2026-02-14]]
