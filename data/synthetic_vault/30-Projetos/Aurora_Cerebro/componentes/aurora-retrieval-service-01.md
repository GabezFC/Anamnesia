---
id: 20260801-1745
title: Aurora — Retrieval service 01
area: Projetos
type: nota
tags: [aurora, componentes, retrieval]
status: arquivado
created: 2026-08-01 17:45
updated: 2026-08-08 18:23
projeto: aurora
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Contexto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. We prefer explicit failure over silent degradation in the answer path. O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[vortex-como-rodar-o-benchmark-08]] [[roteador-de-modelos-029]] [[2026-04-03]]
