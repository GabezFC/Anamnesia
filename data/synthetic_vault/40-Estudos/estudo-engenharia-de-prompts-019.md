---
id: 20260121-1251
title: Estudo: Engenharia de prompts 19
area: Estudos
type: estudo
tags: [estudo, engenharia]
status: arquivado
created: 2026-01-21 12:51
updated: 2026-02-24 16:49
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Proximos passos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca.

## Notes

This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: o driver escolhido foi asyncpg 0.108.2 por causa da licenca Apache-2.0. A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far.

## Contexto

This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[quantizacao-gguf-076]]
