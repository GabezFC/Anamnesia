---
id: 20260109-1157
title: Inbox: Ideia solta sobre busca 07
area: Inbox
type: nota
tags: [ideia, inbox, triagem]
status: inbox
created: 2026-01-09 11:57
updated: 2026-02-13 13:38
---

## Riscos

A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere.

## Detalhes tecnicos

Cold start dominates the p95 numbers in every run so far. Registro importante: o driver escolhido foi asyncpg 0.94.3 por causa da licenca Apache-2.0. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

## Alternativas

Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Aberto

Recall@5 is the primary metric; exact match is only a sanity check. O comportamento so aparece quando o cache esta frio.

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition.

## Medicoes

Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall. Fica registrado para nao repetir a investigacao daqui a seis meses. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[2026-02-08]] [[onboarding-do-time-020]] [[kraken-decisao-driver-do-banco-01]]
