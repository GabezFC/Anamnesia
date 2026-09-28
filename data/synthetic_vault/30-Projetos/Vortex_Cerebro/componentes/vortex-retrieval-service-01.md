---
id: 20261109-0925
title: Vortex — Retrieval service 01
area: Projetos
type: nota
tags: [vortex, componentes, retrieval]
status: arquivado
created: 2026-11-09 09:25
updated: 2026-12-23 12:41
projeto: vortex
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Decisao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. We prefer explicit failure over silent degradation in the answer path. A causa raiz estava na normalizacao dos acentos antes da busca. Latency budget is split between retrieval, rerank and composition.

## Riscos

Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: o driver escolhido foi asyncpg 0.122.1 por causa da licenca Apache-2.0. Vale revisitar isso quando o volume de notas dobrar. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Consequencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. This is a documentation note, not a runbook; keep the steps elsewhere. A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca.

## Medicoes

We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[vortex-decisao-estrategia-de-cache-03]] [[aurora-decisao-driver-do-banco-01]] [[2026-03-19]]
