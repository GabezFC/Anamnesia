---
id: 20261017-1514
title: Vortex — Fluxo de consulta 08
area: Projetos
type: nota
tags: [vortex, arquitetura, fluxo]
status: ativo
created: 2026-10-17 15:14
updated: 2026-11-04 17:01
projeto: vortex
---

## Aberto

Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

## Implementacao

O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses. Latency budget is split between retrieval, rerank and composition. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

Vale revisitar isso quando o volume de notas dobrar. Latency budget is split between retrieval, rerank and composition.

## Detalhes tecnicos

We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Referencias

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[auditoria-de-acessos-022]] [[reuniao-de-alinhamento-025]] [[tokenizer-custom-064]] [[2026-05-09]]
