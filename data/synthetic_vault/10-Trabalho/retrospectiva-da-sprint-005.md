---
id: 20260216-1523
title: Retrospectiva da sprint 05
area: Trabalho
type: nota
tags: [trabalho, retrospectiva, cliente-acme]
status: ativo
created: 2026-02-16 15:23
updated: 2026-03-28 16:44
---

## Medicoes

O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall. The retrieval layer keeps a small LRU in front of the vector index.

## Decisao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

## Implementacao

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall.

## Resumo

Latency budget is split between retrieval, rerank and composition. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[relatorio-para-stakeholders-009]]
