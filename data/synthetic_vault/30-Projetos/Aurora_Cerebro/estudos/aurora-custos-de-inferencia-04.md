---
id: 20260814-1546
title: Aurora — Custos de inferencia 04
area: Projetos
type: estudo
tags: [aurora, estudos, custos]
status: ativo
created: 2026-08-14 15:46
updated: 2026-09-05 22:25
projeto: aurora
---

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Contexto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Alternativas

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Vale revisitar isso quando o volume de notas dobrar.

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[quantizacao-gguf-036]] [[estudo-grafos-de-conhecimento-002]]
