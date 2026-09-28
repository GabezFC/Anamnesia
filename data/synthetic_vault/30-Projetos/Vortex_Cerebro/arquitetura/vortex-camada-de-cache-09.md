---
id: 20261018-1551
title: Vortex — Camada de cache 09
area: Projetos
type: nota
tags: [vortex, arquitetura, camada]
status: ativo
created: 2026-10-18 15:51
updated: 2026-11-14 22:33
projeto: vortex
---

## Riscos

Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far.

## Como reproduzir

We prefer explicit failure over silent degradation in the answer path. Registro importante: o driver escolhido foi asyncpg 0.115.4 por causa da licenca Apache-2.0. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Detalhes tecnicos

Cold start dominates the p95 numbers in every run so far. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Proximos passos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. We prefer explicit failure over silent degradation in the answer path.

## Alternativas

We prefer explicit failure over silent degradation in the answer path. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[handoff-do-time-027]]
