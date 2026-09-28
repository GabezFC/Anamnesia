---
id: 20260819-0851
title: Aurora — Hnsw na pratica 09
area: Projetos
type: estudo
tags: [aurora, estudos, hnsw]
status: ativo
created: 2026-08-19 08:51
updated: 2026-09-03 16:13
projeto: aurora
---

## Notes

Latency budget is split between retrieval, rerank and composition. Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Como reproduzir

We prefer explicit failure over silent degradation in the answer path. Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Implementacao

A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path.

## Consequencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[inbox-rascunho-de-api-020]] [[inbox-esboco-de-experimento-006]] [[roteador-de-modelos-029]] [[contrato-do-fornecedor-019]]
