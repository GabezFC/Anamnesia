---
id: 20260311-1304
title: Controle de gastos 18
area: Pessoal
type: nota
tags: [pessoal, controle]
status: ativo
created: 2026-03-11 13:04
updated: 2026-03-24 17:02
---

## Proximos passos

This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca.

## Riscos

This is a documentation note, not a runbook; keep the steps elsewhere. Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition.

## Alternativas

Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall.

## Como reproduzir

Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Implementacao

We prefer explicit failure over silent degradation in the answer path. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[vortex-como-publicar-release-10]] [[2026-06-11]] [[kraken-avaliacao-com-juiz-llm-05]]
