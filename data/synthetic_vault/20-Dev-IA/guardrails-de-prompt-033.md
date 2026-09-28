---
id: 20260515-0939
title: Guardrails de prompt 33
area: Dev-IA
type: nota
tags: [dev, ia, guardrails]
status: ativo
created: 2026-05-15 09:39
updated: 2026-05-20 17:33
---

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

## Notes

Latency budget is split between retrieval, rerank and composition. A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Consequencias

This is a documentation note, not a runbook; keep the steps elsewhere. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[kraken-cache-layer-02]] [[estudo-amostragem-e-vies-035]] [[politica-de-dados-011]] [[reranker-local-063]]
