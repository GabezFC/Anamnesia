---
id: 20260711-1448
title: Aurora — Integracao com o vault 10
area: Projetos
type: nota
tags: [aurora, arquitetura, integracao]
status: arquivado
created: 2026-07-11 14:48
updated: 2026-08-22 15:41
projeto: aurora
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Proximos passos

Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Resumo

Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Notes

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Como reproduzir

O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far.

## Aberto

Cold start dominates the p95 numbers in every run so far. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[2026-03-13]]
