---
id: 20260918-1721
title: Kraken — Regerar o grafo 09
area: Projetos
type: nota
tags: [kraken, procedimentos, regerar]
status: ativo
created: 2026-09-18 17:21
updated: 2026-09-24 22:26
projeto: kraken
---

## Aberto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. We prefer explicit failure over silent degradation in the answer path.

## Alternativas

A causa raiz estava na normalizacao dos acentos antes da busca. This is a documentation note, not a runbook; keep the steps elsewhere. We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Riscos

Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[pipeline-de-ingestao-022]] [[estudo-sistemas-distribuidos-004]] [[pipeline-de-ingestao-042]]
