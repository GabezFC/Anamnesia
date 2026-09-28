---
id: 20260612-1655
title: Cache de embeddings 61
area: Dev-IA
type: decisao
tags: [dev, ia, cache]
status: ativo
created: 2026-06-12 16:55
updated: 2026-07-19 21:59
---

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Resumo

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere. Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[observabilidade-de-agentes-068]] [[auditoria-de-acessos-022]] [[estudo-metricas-de-ranqueamento-022]] [[vortex-decisao-modelo-local-padrao-06]]
