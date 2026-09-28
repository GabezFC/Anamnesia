---
id: 20261014-1323
title: Vortex — Modulo de ranqueamento 05
area: Projetos
type: nota
tags: [vortex, arquitetura, modulo]
status: ativo
created: 2026-10-14 13:23
updated: 2026-11-19 15:57
projeto: vortex
---

## Consequencias

Vale revisitar isso quando o volume de notas dobrar. O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Referencias

Latency budget is split between retrieval, rerank and composition. A decisao foi tomada depois de comparar tres alternativas equivalentes. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

The retrieval layer keeps a small LRU in front of the vector index. A ideia central e reduzir o custo de contexto sem perder recall.

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar.

## Decisao

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[auditoria-de-acessos-046]] [[2026-06-20]] [[inbox-esboco-de-experimento-018]] [[kraken-cache-layer-02]]
