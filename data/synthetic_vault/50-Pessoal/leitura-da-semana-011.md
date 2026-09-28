---
id: 20260304-0845
title: Leitura da semana 11
area: Pessoal
type: nota
tags: [pessoal, leitura]
status: ativo
created: 2026-03-04 08:45
updated: 2026-03-05 16:51
---

## Contexto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition.

## Medicoes

The retrieval layer keeps a small LRU in front of the vector index. Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Detalhes tecnicos

A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far.

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[aurora-fluxo-de-consulta-08]] [[2026-02-08]] [[kraken-graph-loader-03]]
