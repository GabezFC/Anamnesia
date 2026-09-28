---
id: 20260929-1408
title: Kraken — Answer composer 10
area: Projetos
type: nota
tags: [kraken, componentes, answer]
status: ativo
created: 2026-09-29 14:08
updated: 2026-10-22 17:48
projeto: kraken
---

## Detalhes tecnicos

We prefer explicit failure over silent degradation in the answer path. Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Resumo

Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Consequencias

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Notes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Vale revisitar isso quando o volume de notas dobrar.

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A ideia central e reduzir o custo de contexto sem perder recall.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[kraken-cache-layer-08]]
