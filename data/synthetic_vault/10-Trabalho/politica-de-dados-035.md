---
id: 20260318-1353
title: Politica de dados 35
area: Trabalho
type: nota
tags: [trabalho, politica, cliente-acme]
status: ativo
created: 2026-03-18 13:53
updated: 2026-03-21 15:56
---

## Detalhes tecnicos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall.

## Consequencias

O comportamento so aparece quando o cache esta frio. Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Implementacao

This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far.

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[habitos-de-foco-007]] [[estudo-sistemas-distribuidos-028]]
