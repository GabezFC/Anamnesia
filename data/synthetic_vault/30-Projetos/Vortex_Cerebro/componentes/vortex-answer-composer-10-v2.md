---
id: 20261129-1505
title: Vortex — Answer composer 10
area: Projetos
type: nota
tags: [vortex, componentes, answer]
status: ativo
created: 2026-11-29 15:05
updated: 2027-01-05 15:46
projeto: vortex
---

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. Latency budget is split between retrieval, rerank and composition. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Referencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall.

## Notes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[inbox-anotacao-de-podcast-015]] [[roteador-de-modelos-049]]
