---
id: 20260823-1439
title: Aurora — Conceitos de bm25 02
area: Projetos
type: estudo
tags: [aurora, estudos, conceitos]
status: arquivado
created: 2026-08-23 14:39
updated: 2026-10-13 17:02
projeto: aurora
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Consequencias

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio.

## Contexto

This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Detalhes tecnicos

Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[2026-04-21]] [[kraken-cache-layer-02]]
