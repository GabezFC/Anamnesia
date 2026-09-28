---
id: 20261029-1238
title: Vortex — Biblioteca de embeddings 10
area: Projetos
type: decisao
tags: [vortex, decisoes, biblioteca]
status: ativo
created: 2026-10-29 12:38
updated: 2026-11-19 13:25
projeto: vortex
---

## Aberto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: a dependencia critica aqui e a lib Trivandex 7.115.3, que substituiu o parser antigo. Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Decisao

Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Contexto

Em teste local o ganho apareceu principalmente nas consultas curtas. Latency budget is split between retrieval, rerank and composition.

## Referencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[contrato-do-fornecedor-019]] [[inbox-rascunho-de-api-020]] [[2026-04-15]]
