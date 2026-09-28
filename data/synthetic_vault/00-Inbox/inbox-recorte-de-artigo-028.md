---
id: 20260130-1454
title: Inbox: Recorte de artigo 28
area: Inbox
type: nota
tags: [recorte, inbox, triagem]
status: inbox
created: 2026-01-30 14:54
updated: 2026-03-05 21:07
---

## Proximos passos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Latency budget is split between retrieval, rerank and composition.

## Decisao

We prefer explicit failure over silent degradation in the answer path. Registro importante: o driver escolhido foi asyncpg 0.87.1 por causa da licenca Apache-2.0. Deduplication happens before rerank, otherwise near-duplicates flood the top. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[aurora-licencas-das-dependencias-07]] [[aurora-answer-composer-04]]
