---
id: 20260927-1254
title: Kraken — Cache layer 08
area: Projetos
type: nota
tags: [kraken, componentes, cache]
status: ativo
created: 2026-09-27 12:54
updated: 2026-10-31 18:45
projeto: kraken
---

## Contexto

Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o identificador interno do experimento e Trivandex-7095 e ele nao deve ser renomeado. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Implementacao

This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[retrospectiva-da-sprint-029]] [[retrospectiva-da-sprint-017]] [[inbox-ideia-solta-sobre-busca-031]] [[parser-de-frontmatter-079]]
