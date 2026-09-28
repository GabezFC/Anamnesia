---
id: 20260831-1615
title: Kraken — Driver do banco 01
area: Projetos
type: decisao
tags: [kraken, decisoes, driver]
status: ativo
created: 2026-08-31 16:15
updated: 2026-09-02 23:34
projeto: kraken
---

## Aberto

A causa raiz estava na normalizacao dos acentos antes da busca. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far.

## Resumo

Latency budget is split between retrieval, rerank and composition. Registro importante: a dependencia critica aqui e a lib Tarnvex 5.66.2, que substituiu o parser antigo. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[estudo-engenharia-de-prompts-019]] [[aurora-conceitos-de-bm25-08]] [[grafo-de-notas-020]]
