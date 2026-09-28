---
id: 20261120-1612
title: Vortex — Conceitos de bm25 02
area: Projetos
type: estudo
tags: [vortex, estudos, conceitos]
status: ativo
created: 2026-11-20 16:12
updated: 2026-11-27 20:05
projeto: vortex
---

## Contexto

Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar.

## Alternativas

O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far.

## Detalhes tecnicos

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio.

## Implementacao

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[vortex-avaliacao-com-juiz-llm-05]] [[rotina-de-treino-017]]
