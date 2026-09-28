---
id: 20260325-1812
title: Orcamento de infra 42
area: Trabalho
type: nota
tags: [trabalho, orcamento, cliente-acme]
status: ativo
created: 2026-03-25 18:12
updated: 2026-05-06 22:15
---

## Medicoes

Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Riscos

O comportamento so aparece quando o cache esta frio. We prefer explicit failure over silent degradation in the answer path. Latency budget is split between retrieval, rerank and composition. We prefer explicit failure over silent degradation in the answer path.

## Implementacao

Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[estudo-algebra-linear-aplicada-015]] [[aurora-modulo-de-ranqueamento-05]] [[kraken-retrieval-service-01]] [[batch-de-inferencia-055]]
