---
id: 20260225-1056
title: Revisao de escopo 14
area: Trabalho
type: nota
tags: [trabalho, revisao, cliente-acme]
status: arquivado
created: 2026-02-25 10:56
updated: 2026-03-31 17:20
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Medicoes

We prefer explicit failure over silent degradation in the answer path. Vale revisitar isso quando o volume de notas dobrar.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Proximos passos

Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far.

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far.

## Implementacao

A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Aberto

This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition.

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[kraken-como-rodar-o-benchmark-02]] [[politica-de-dados-047]] [[handoff-do-time-003]] [[vortex-decisao-driver-do-banco-01]]
