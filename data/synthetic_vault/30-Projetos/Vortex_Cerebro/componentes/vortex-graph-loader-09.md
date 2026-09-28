---
id: 20261117-1421
title: Vortex — Graph loader 09
area: Projetos
type: nota
tags: [vortex, componentes, graph]
status: ativo
created: 2026-11-17 14:21
updated: 2026-12-31 18:46
projeto: vortex
---

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar.

## Detalhes tecnicos

Recall@5 is the primary metric; exact match is only a sanity check. O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[vortex-conceitos-de-bm25-08]] [[parser-de-frontmatter-079]]
