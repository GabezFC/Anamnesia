---
id: 20260723-1212
title: Aurora — Rodar o benchmark 02
area: Projetos
type: nota
tags: [aurora, procedimentos, rodar]
status: ativo
created: 2026-07-23 12:12
updated: 2026-07-26 12:59
projeto: aurora
---

## Aberto

Deduplication happens before rerank, otherwise near-duplicates flood the top. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. The retrieval layer keeps a small LRU in front of the vector index.

## Contexto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Latency budget is split between retrieval, rerank and composition. Vale revisitar isso quando o volume de notas dobrar.

## Riscos

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[2026-06-29]] [[revisao-de-escopo-038]] [[2026-04-24]]
