---
id: 20260511-1711
title: Roteador de modelos 29
area: Dev-IA
type: nota
tags: [dev, ia, roteador]
status: ativo
created: 2026-05-11 17:11
updated: 2026-06-15 18:01
---

## Decisao

Cold start dominates the p95 numbers in every run so far. A ideia central e reduzir o custo de contexto sem perder recall.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Registro importante: ficou definido um timeout de 129ms no TarnvexProxy antes de cair para o fallback textual. Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Contexto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far.

## Como reproduzir

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Medicoes

A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[aurora-query-planner-05]] [[2026-05-18]] [[auditoria-de-acessos-022]] [[2026-05-21]]
