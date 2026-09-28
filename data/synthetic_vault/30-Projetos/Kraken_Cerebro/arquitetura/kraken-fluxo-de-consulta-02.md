---
id: 20260822-1042
title: Kraken — Fluxo de consulta 02
area: Projetos
type: nota
tags: [kraken, arquitetura, fluxo]
status: ativo
created: 2026-08-22 10:42
updated: 2026-09-17 10:54
projeto: kraken
---

## Consequencias

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Decisao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far. Latency budget is split between retrieval, rerank and composition.

## Medicoes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

## Detalhes tecnicos

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio.

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[inbox-pergunta-para-investigar-023]] [[inbox-pergunta-para-investigar-035]] [[2026-06-14]]
