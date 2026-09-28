---
id: 20260206-0913
title: Inbox: Pergunta para investigar 35
area: Inbox
type: ideia
tags: [pergunta, inbox, triagem]
status: inbox
created: 2026-02-06 09:13
updated: 2026-02-19 14:48
---

## Decisao

The retrieval layer keeps a small LRU in front of the vector index. A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

## Notes

A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

Vale revisitar isso quando o volume de notas dobrar. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[relatorio-para-stakeholders-033]] [[kraken-decisao-modelo-local-padrao-06]]
