---
id: 20261123-1803
title: Vortex — Avaliacao com juiz llm 05
area: Projetos
type: estudo
tags: [vortex, estudos, avaliacao]
status: ativo
created: 2026-11-23 18:03
updated: 2026-12-26 22:49
projeto: vortex
---

## Medicoes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. We prefer explicit failure over silent degradation in the answer path.

## Alternativas

Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Aberto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

## Detalhes tecnicos

We prefer explicit failure over silent degradation in the answer path. Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Riscos

A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Consequencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[kraken-vault-watcher-06]] [[vortex-como-publicar-release-10]] [[roteador-de-modelos-029]]
