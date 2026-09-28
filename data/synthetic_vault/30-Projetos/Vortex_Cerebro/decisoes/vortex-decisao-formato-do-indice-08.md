---
id: 20261027-1124
title: Vortex — Formato do indice 08
area: Projetos
type: decisao
tags: [vortex, decisoes, formato]
status: ativo
created: 2026-10-27 11:24
updated: 2026-11-28 17:03
projeto: vortex
---

## Medicoes

The retrieval layer keeps a small LRU in front of the vector index. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

A causa raiz estava na normalizacao dos acentos antes da busca. A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: o identificador interno do experimento e Brintiq-7011 e ele nao deve ser renomeado. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check.

## Referencias

A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition. O comportamento so aparece quando o cache esta frio. O comportamento so aparece quando o cache esta frio.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Latency budget is split between retrieval, rerank and composition. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[estudo-information-retrieval-013]] [[cache-de-embeddings-041]] [[aurora-como-subir-o-ambiente-01]]
