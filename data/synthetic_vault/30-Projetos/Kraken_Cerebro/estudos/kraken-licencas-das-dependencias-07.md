---
id: 20261006-0827
title: Kraken — Licencas das dependencias 07
area: Projetos
type: estudo
tags: [kraken, estudos, licencas]
status: ativo
created: 2026-10-06 08:27
updated: 2026-10-25 14:08
projeto: kraken
---

## Detalhes tecnicos

Fica registrado para nao repetir a investigacao daqui a seis meses. Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

The retrieval layer keeps a small LRU in front of the vector index. Recall@5 is the primary metric; exact match is only a sanity check.

## Medicoes

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check.

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. Recall@5 is the primary metric; exact match is only a sanity check. A causa raiz estava na normalizacao dos acentos antes da busca.

## Decisao

Deduplication happens before rerank, otherwise near-duplicates flood the top. Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[inbox-esboco-de-experimento-036]] [[cache-de-embeddings-041]]
