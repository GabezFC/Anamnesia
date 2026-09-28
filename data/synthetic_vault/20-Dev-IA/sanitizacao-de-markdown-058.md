---
id: 20260609-1504
title: Sanitizacao de markdown 58
area: Dev-IA
type: nota
tags: [dev, ia, sanitizacao]
status: ativo
created: 2026-06-09 15:04
updated: 2026-06-24 18:30
---

## Detalhes tecnicos

Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index.

## Alternativas

Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: o snapshot foi validado contra KrampusDB v9.139-rc1 em ambiente isolado. O comportamento so aparece quando o cache esta frio.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Como reproduzir

Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[kraken-query-planner-05]]
