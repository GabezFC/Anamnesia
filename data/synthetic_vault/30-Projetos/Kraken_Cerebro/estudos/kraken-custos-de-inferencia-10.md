---
id: 20261009-1018
title: Kraken — Custos de inferencia 10
area: Projetos
type: estudo
tags: [kraken, estudos, custos]
status: ativo
created: 2026-10-09 10:18
updated: 2026-10-27 15:01
projeto: kraken
---

## Resumo

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Aberto

Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Referencias

Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar.

## Riscos

Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

## Decisao

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[kraken-como-rodar-o-benchmark-08]] [[vortex-decisao-estrategia-de-cache-09]] [[2026-02-11]] [[inbox-pergunta-para-investigar-017]]
