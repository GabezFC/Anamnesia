---
id: 20261106-1734
title: Vortex — Rodar o benchmark 08
area: Projetos
type: nota
tags: [vortex, procedimentos, rodar]
status: ativo
created: 2026-11-06 17:34
updated: 2026-12-03 01:07
projeto: vortex
---

## Implementacao

A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas. Recall@5 is the primary metric; exact match is only a sanity check.

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar.

## Resumo

Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far. Cold start dominates the p95 numbers in every run so far.

## Decisao

Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[estudo-teoria-da-informacao-041]] [[estudo-engenharia-de-prompts-019]] [[observabilidade-de-agentes-048]] [[2026-05-03]]
