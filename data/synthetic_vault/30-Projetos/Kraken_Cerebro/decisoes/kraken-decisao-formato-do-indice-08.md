---
id: 20260907-1034
title: Kraken — Formato do indice 08
area: Projetos
type: decisao
tags: [kraken, decisoes, formato]
status: ativo
created: 2026-09-07 10:34
updated: 2026-09-19 13:58
projeto: kraken
---

## Como reproduzir

O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check. A causa raiz estava na normalizacao dos acentos antes da busca.

## Decisao

A decisao foi tomada depois de comparar tres alternativas equivalentes. The retrieval layer keeps a small LRU in front of the vector index. Registro importante: a dependencia critica aqui e a lib Halvexis 3.38.2, que substituiu o parser antigo. A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[aurora-como-rodar-o-benchmark-08]] [[2026-02-23]]
