---
id: 20260121-0921
title: Inbox: Ideia solta sobre busca 19
area: Inbox
type: ideia
tags: [ideia, inbox, triagem]
status: inbox
created: 2026-01-21 09:21
updated: 2026-02-26 10:59
---

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca.

## Consequencias

The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Como reproduzir

This is a documentation note, not a runbook; keep the steps elsewhere. Cold start dominates the p95 numbers in every run so far. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Latency budget is split between retrieval, rerank and composition.

## Medicoes

We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index. We prefer explicit failure over silent degradation in the answer path.

## Referencias

The retrieval layer keeps a small LRU in front of the vector index. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[kraken-fluxo-de-consulta-08]] [[habitos-de-foco-015]] [[fila-de-jobs-046]] [[plano-de-viagem-020]]
