---
id: 20260729-1554
title: Aurora — Rodar o benchmark 08
area: Projetos
type: nota
tags: [aurora, procedimentos, rodar]
status: arquivado
created: 2026-07-29 15:54
updated: 2026-08-26 20:36
projeto: aurora
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Resumo

This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

## Detalhes tecnicos

Deduplication happens before rerank, otherwise near-duplicates flood the top. Registro importante: o snapshot foi validado contra KrampusDB v1.6-rc0 em ambiente isolado. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

The retrieval layer keeps a small LRU in front of the vector index. Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Decisao

Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[vortex-decisao-biblioteca-de-embeddings-04]]
