---
id: 20260228-1247
title: Retrospectiva da sprint 17
area: Trabalho
type: nota
tags: [trabalho, retrospectiva, cliente-acme]
status: ativo
created: 2026-02-28 12:47
updated: 2026-03-07 15:17
---

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. Latency budget is split between retrieval, rerank and composition.

## Detalhes tecnicos

A ideia central e reduzir o custo de contexto sem perder recall. Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Notes

Recall@5 is the primary metric; exact match is only a sanity check. Vale revisitar isso quando o volume de notas dobrar. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere.

## Proximos passos

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[vortex-anatomia-do-frontmatter-06]]
