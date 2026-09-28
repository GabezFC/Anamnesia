---
id: 20260509-1557
title: Retry com backoff 27
area: Dev-IA
type: nota
tags: [dev, ia, retry]
status: ativo
created: 2026-05-09 15:57
updated: 2026-06-07 18:04
---

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Aberto

Recall@5 is the primary metric; exact match is only a sanity check. Recall@5 is the primary metric; exact match is only a sanity check. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[vortex-camada-de-cache-03]] [[aurora-como-subir-o-ambiente-07]]
