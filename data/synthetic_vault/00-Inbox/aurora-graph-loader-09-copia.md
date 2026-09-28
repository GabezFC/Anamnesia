---
id: 20260809-1241
title: Aurora — Graph loader 09
area: Projetos
type: nota
tags: [aurora, componentes, graph]
status: ativo
created: 2026-08-09 12:41
updated: 2026-09-01 20:21
projeto: aurora
---

## Implementacao

Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

Deduplication happens before rerank, otherwise near-duplicates flood the top. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index.

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Como reproduzir

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check.

## Consequencias

A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[orcamento-mensal-024]] [[inbox-esboco-de-experimento-036]]
