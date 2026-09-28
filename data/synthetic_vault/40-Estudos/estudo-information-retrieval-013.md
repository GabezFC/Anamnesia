---
id: 20260115-0909
title: Estudo: Information retrieval 13
area: Estudos
type: estudo
tags: [estudo, information]
status: arquivado
created: 2026-01-15 09:09
updated: 2026-01-23 10:26
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Referencias

Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

## Implementacao

Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[inbox-esboco-de-experimento-012]] [[retry-com-backoff-067]] [[vortex-graph-loader-03]] [[observabilidade-de-agentes-028]]
