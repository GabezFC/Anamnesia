---
id: 20261127-1031
title: Vortex — Hnsw na pratica 09
area: Projetos
type: estudo
tags: [vortex, estudos, hnsw]
status: ativo
created: 2026-11-27 10:31
updated: 2027-01-01 14:19
projeto: vortex
---

## Implementacao

A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Alternativas

A ideia central e reduzir o custo de contexto sem perder recall. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. We prefer explicit failure over silent degradation in the answer path. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Decisao

Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[2026-03-28]] [[2026-04-15]] [[auditoria-de-acessos-022]] [[inbox-pergunta-para-investigar-029]]
