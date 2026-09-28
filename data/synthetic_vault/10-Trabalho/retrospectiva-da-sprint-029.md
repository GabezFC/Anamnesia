---
id: 20260312-1011
title: Retrospectiva da sprint 29
area: Trabalho
type: nota
tags: [trabalho, retrospectiva, cliente-acme]
status: ativo
created: 2026-03-12 10:11
updated: 2026-04-14 18:01
---

## Contexto

Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar.

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio. O comportamento so aparece quando o cache esta frio.

## Medicoes

Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

## Aberto

Latency budget is split between retrieval, rerank and composition. Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Alternativas

Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses. A causa raiz estava na normalizacao dos acentos antes da busca. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[chunking-hibrido-011]] [[relatorio-para-stakeholders-057]] [[pipeline-de-ingestao-042]]
