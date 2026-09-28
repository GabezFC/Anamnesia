---
id: 20260913-1416
title: Kraken — Publicar release 04
area: Projetos
type: nota
tags: [kraken, procedimentos, publicar]
status: ativo
created: 2026-09-13 14:16
updated: 2026-10-17 17:05
projeto: kraken
---

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall.

## Resumo

A decisao foi tomada depois de comparar tres alternativas equivalentes. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[inbox-rascunho-de-api-002]] [[estudo-information-retrieval-049]]
