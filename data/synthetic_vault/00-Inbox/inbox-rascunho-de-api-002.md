---
id: 20260104-0852
title: Inbox: Rascunho de api 02
area: Inbox
type: ideia
tags: [rascunho, inbox, triagem]
status: inbox
created: 2026-01-04 08:52
updated: 2026-01-19 10:46
---

## Implementacao

Vale revisitar isso quando o volume de notas dobrar. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

Recall@5 is the primary metric; exact match is only a sanity check. Registro importante: o identificador interno do experimento e Wexpolium-7116 e ele nao deve ser renomeado. O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Latency budget is split between retrieval, rerank and composition. Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[estudo-algebra-linear-aplicada-003]]
