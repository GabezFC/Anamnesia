---
id: 20260310-1227
title: Rotina de treino 17
area: Pessoal
type: nota
tags: [pessoal, rotina]
status: arquivado
created: 2026-03-10 12:27
updated: 2026-04-15 20:32
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Proximos passos

Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. A causa raiz estava na normalizacao dos acentos antes da busca.

## Referencias

Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[cache-de-embeddings-061]]
