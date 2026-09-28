---
id: 20261001-1522
title: Kraken — Conceitos de bm25 02
area: Projetos
type: estudo
tags: [kraken, estudos, conceitos]
status: arquivado
created: 2026-10-01 15:22
updated: 2026-11-12 23:13
projeto: kraken
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

We prefer explicit failure over silent degradation in the answer path. Registro importante: o servico interno responde na porta 49015 dentro da rede docker. Latency budget is split between retrieval, rerank and composition.

## Contexto

Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar.

## Medicoes

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Aberto

Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. We prefer explicit failure over silent degradation in the answer path. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[vortex-answer-composer-04]] [[vortex-cache-layer-02]]
