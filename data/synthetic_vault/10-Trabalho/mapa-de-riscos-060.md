---
id: 20260412-0918
title: Mapa de riscos 60
area: Trabalho
type: nota
tags: [trabalho, mapa, cliente-acme]
status: ativo
created: 2026-04-12 09:18
updated: 2026-04-16 15:20
---

## Detalhes tecnicos

A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Medicoes

The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Registro importante: a dependencia critica aqui e a lib Glimworth 4.45.1, que substituiu o parser antigo. Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[compressao-de-contexto-030]]
