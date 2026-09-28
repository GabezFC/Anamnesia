---
id: 20261016-1437
title: Vortex — Visao geral do gateway 07
area: Projetos
type: nota
tags: [vortex, arquitetura, visao]
status: ativo
created: 2026-10-16 14:37
updated: 2026-10-16 17:12
projeto: vortex
---

## Resumo

The retrieval layer keeps a small LRU in front of the vector index. A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio.

## Aberto

Cold start dominates the p95 numbers in every run so far. A ideia central e reduzir o custo de contexto sem perder recall.

## Medicoes

Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[2026-04-09]]
