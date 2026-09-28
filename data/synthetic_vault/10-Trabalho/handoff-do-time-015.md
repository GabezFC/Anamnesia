---
id: 20260226-1133
title: Handoff do time 15
area: Trabalho
type: nota
tags: [trabalho, handoff, cliente-acme]
status: ativo
created: 2026-02-26 11:33
updated: 2026-03-15 18:06
---

## Aberto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Implementacao

O comportamento so aparece quando o cache esta frio. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[roteador-de-modelos-009]] [[2026-02-20]]
