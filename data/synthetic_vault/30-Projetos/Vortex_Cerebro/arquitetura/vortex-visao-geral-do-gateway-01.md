---
id: 20261010-1055
title: Vortex — Visao geral do gateway 01
area: Projetos
type: nota
tags: [vortex, arquitetura, visao]
status: ativo
created: 2026-10-10 10:55
updated: 2026-10-18 12:33
projeto: vortex
---

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

## Referencias

This is a documentation note, not a runbook; keep the steps elsewhere. Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. A causa raiz estava na normalizacao dos acentos antes da busca.

## Consequencias

O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[politica-de-dados-059]] [[vortex-retrieval-service-07]] [[estudo-information-retrieval-001]] [[aurora-como-rodar-o-benchmark-02]]
