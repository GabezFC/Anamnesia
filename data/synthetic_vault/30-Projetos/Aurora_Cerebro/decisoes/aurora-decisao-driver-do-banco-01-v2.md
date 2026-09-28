---
id: 20260723-1532
title: Aurora — Driver do banco 01
area: Projetos
type: decisao
tags: [aurora, decisoes, driver]
status: ativo
created: 2026-07-23 15:32
updated: 2026-08-08 18:03
projeto: aurora
---

## Medicoes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall.

## Referencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

## Como reproduzir

Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[pipeline-de-ingestao-002]] [[planejamento-trimestral-004]] [[aurora-answer-composer-04]]
