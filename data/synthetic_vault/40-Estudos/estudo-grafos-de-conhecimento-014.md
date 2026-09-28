---
id: 20260116-0946
title: Estudo: Grafos de conhecimento 14
area: Estudos
type: estudo
tags: [estudo, grafos]
status: arquivado
created: 2026-01-16 09:46
updated: 2026-01-30 13:02
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

## Alternativas

We prefer explicit failure over silent degradation in the answer path. Registro importante: o driver escolhido foi asyncpg 0.150.4 por causa da licenca Apache-2.0. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Proximos passos

Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[estudo-estatistica-bayesiana-042]] [[2026-05-27]] [[reranker-local-023]]
