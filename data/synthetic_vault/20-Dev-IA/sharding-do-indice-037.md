---
id: 20260519-1207
title: Sharding do indice 37
area: Dev-IA
type: nota
tags: [dev, ia, sharding]
status: ativo
created: 2026-05-19 12:07
updated: 2026-06-13 19:49
---

## Notes

Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check.

## Consequencias

Recall@5 is the primary metric; exact match is only a sanity check. Registro importante: o servico interno responde na porta 49134 dentro da rede docker. A ideia central e reduzir o custo de contexto sem perder recall. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Resumo

A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall.

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. We prefer explicit failure over silent degradation in the answer path. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[rotina-de-treino-009]] [[indice-vetorial-005]]
