---
id: 20260303-1438
title: Onboarding do time 20
area: Trabalho
type: nota
tags: [trabalho, onboarding, cliente-acme]
status: ativo
created: 2026-03-03 14:38
updated: 2026-03-19 22:55
---

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

## Medicoes

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[retry-com-backoff-007]] [[kraken-retrieval-service-07]] [[vortex-cache-layer-02]]
