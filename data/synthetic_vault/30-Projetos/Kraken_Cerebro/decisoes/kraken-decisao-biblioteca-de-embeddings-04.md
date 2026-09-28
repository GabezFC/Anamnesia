---
id: 20260903-1806
title: Kraken — Biblioteca de embeddings 04
area: Projetos
type: decisao
tags: [kraken, decisoes, biblioteca]
status: ativo
created: 2026-09-03 18:06
updated: 2026-10-02 21:05
projeto: kraken
---

## Alternativas

A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Referencias

The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far.

## Detalhes tecnicos

The retrieval layer keeps a small LRU in front of the vector index. Cold start dominates the p95 numbers in every run so far.

## Implementacao

This is a documentation note, not a runbook; keep the steps elsewhere. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Contexto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[parser-de-frontmatter-059]] [[kraken-como-regerar-o-grafo-09]] [[estudo-compiladores-e-ast-024]]
