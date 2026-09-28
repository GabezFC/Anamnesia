---
id: 20260710-1411
title: Aurora — Camada de cache 09
area: Projetos
type: nota
tags: [aurora, arquitetura, camada]
status: ativo
created: 2026-07-10 14:11
updated: 2026-08-14 16:44
projeto: aurora
---

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far. Latency budget is split between retrieval, rerank and composition. Vale revisitar isso quando o volume de notas dobrar.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: ficou definido um timeout de 115ms no KlovexaProxy antes de cair para o fallback textual. Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. Em teste local o ganho apareceu principalmente nas consultas curtas. This is a documentation note, not a runbook; keep the steps elsewhere.

## Detalhes tecnicos

Cold start dominates the p95 numbers in every run so far. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[estudo-grafos-de-conhecimento-002]]
