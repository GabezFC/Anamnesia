---
id: 20261028-1201
title: Vortex — Estrategia de cache 09
area: Projetos
type: decisao
tags: [vortex, decisoes, estrategia]
status: arquivado
created: 2026-10-28 12:01
updated: 2026-12-07 17:18
projeto: vortex
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Proximos passos

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Resumo

Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path.

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Detalhes tecnicos

Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index.

Relacionadas: [[aurora-como-rodar-o-benchmark-02]] [[inbox-pergunta-para-investigar-035]] [[2026-04-03]]
