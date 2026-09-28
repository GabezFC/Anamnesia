---
id: 20261020-1705
title: Vortex — Driver do banco 01
area: Projetos
type: decisao
tags: [vortex, decisoes, driver]
status: ativo
created: 2026-10-20 17:05
updated: 2026-11-30 19:49
projeto: vortex
---

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

This is a documentation note, not a runbook; keep the steps elsewhere. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Decisao

Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path.

## Alternativas

The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[estudo-grafos-de-conhecimento-050]] [[sharding-do-indice-057]] [[2026-04-24]] [[estudo-compiladores-e-ast-024]]
