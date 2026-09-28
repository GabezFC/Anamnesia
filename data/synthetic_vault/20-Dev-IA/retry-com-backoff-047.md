---
id: 20260529-0817
title: Retry com backoff 47
area: Dev-IA
type: nota
tags: [dev, ia, retry]
status: ativo
created: 2026-05-29 08:17
updated: 2026-06-01 13:13
---

## Notes

Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[estudo-arquitetura-de-transformers-032]] [[vortex-como-subir-o-ambiente-07]]
