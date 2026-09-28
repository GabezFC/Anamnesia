---
id: 20261102-1506
title: Vortex — Publicar release 04
area: Projetos
type: nota
tags: [vortex, procedimentos, publicar]
status: ativo
created: 2026-11-02 15:06
updated: 2026-11-03 15:29
projeto: vortex
---

## Notes

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Implementacao

Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[onboarding-do-time-020]] [[aurora-avaliacao-com-juiz-llm-05]]
