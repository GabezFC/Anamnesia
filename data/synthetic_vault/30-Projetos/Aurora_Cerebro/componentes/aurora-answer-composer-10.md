---
id: 20260810-1318
title: Aurora — Answer composer 10
area: Projetos
type: nota
tags: [aurora, componentes, answer]
status: ativo
created: 2026-08-10 13:18
updated: 2026-08-12 20:58
projeto: aurora
---

## Contexto

Latency budget is split between retrieval, rerank and composition. We prefer explicit failure over silent degradation in the answer path. A ideia central e reduzir o custo de contexto sem perder recall.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Implementacao

Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: a dependencia critica aqui e a lib KrampusDB 7.101.1, que substituiu o parser antigo. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Consequencias

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

## Resumo

Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[revisao-de-escopo-050]] [[guardrails-de-prompt-013]] [[2026-06-14]]
