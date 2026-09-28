---
id: 20260126-1556
title: Estudo: Compiladores e ast 24
area: Estudos
type: estudo
tags: [estudo, compiladores]
status: ativo
created: 2026-01-26 15:56
updated: 2026-03-11 16:06
---

## Aberto

Fica registrado para nao repetir a investigacao daqui a seis meses. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Consequencias

The retrieval layer keeps a small LRU in front of the vector index. Registro importante: o snapshot foi validado contra KrampusDB v3.34-rc1 em ambiente isolado. Recall@5 is the primary metric; exact match is only a sanity check. This is a documentation note, not a runbook; keep the steps elsewhere.

## Referencias

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[2026-04-30]] [[cache-de-embeddings-041]] [[handoff-do-time-015]] [[inbox-anotacao-de-podcast-039]]
