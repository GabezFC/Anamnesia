---
id: 20260725-1326
title: Aurora — Publicar release 04
area: Projetos
type: nota
tags: [aurora, procedimentos, publicar]
status: arquivado
created: 2026-07-25 13:26
updated: 2026-08-11 13:48
projeto: aurora
---

> DESATUALIZADO: os numeros abaixo vieram de uma medicao antiga e nao valem mais.

## Implementacao

The retrieval layer keeps a small LRU in front of the vector index. Ajuste na revisao: o paragrafo foi reescrito nesta versao do documento. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Riscos

We prefer explicit failure over silent degradation in the answer path. Nota da revisao: o trecho original foi trocado por esta formulacao equivalente. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Medicoes

O comportamento so aparece quando o cache esta frio. This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Contexto

A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top. This is a documentation note, not a runbook; keep the steps elsewhere. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[politica-de-dados-035]] [[orcamento-mensal-016]] [[inbox-esboco-de-experimento-006]] [[estudo-algebra-linear-aplicada-039]]
