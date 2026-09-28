---
id: 20260319-1430
title: Mapa de riscos 36
area: Trabalho
type: nota
tags: [trabalho, mapa, cliente-acme]
status: ativo
created: 2026-03-19 14:30
updated: 2026-04-24 22:34
---

## Implementacao

O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Medicoes

A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Alternativas

A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[indice-vetorial-065]] [[estudo-arquitetura-de-transformers-044]] [[2026-02-14]]
