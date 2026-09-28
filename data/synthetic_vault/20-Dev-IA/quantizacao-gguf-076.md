---
id: 20260627-1610
title: Quantizacao gguf 76
area: Dev-IA
type: decisao
tags: [dev, ia, quantizacao]
status: ativo
created: 2026-06-27 16:10
updated: 2026-08-02 17:01
---

## Medicoes

This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition. This is a documentation note, not a runbook; keep the steps elsewhere.

## Decisao

Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Riscos

O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Consequencias

O comportamento so aparece quando o cache esta frio. This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Alternativas

The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar.

## Aberto

Fica registrado para nao repetir a investigacao daqui a seis meses. Deduplication happens before rerank, otherwise near-duplicates flood the top. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[kraken-custos-de-inferencia-10]] [[fila-de-jobs-066]]
