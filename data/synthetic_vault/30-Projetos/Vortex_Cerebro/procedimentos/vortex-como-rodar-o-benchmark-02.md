---
id: 20261031-1352
title: Vortex — Rodar o benchmark 02
area: Projetos
type: nota
tags: [vortex, procedimentos, rodar]
status: ativo
created: 2026-10-31 13:52
updated: 2026-11-19 15:47
projeto: vortex
---

## Consequencias

This is a documentation note, not a runbook; keep the steps elsewhere. Cold start dominates the p95 numbers in every run so far. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Proximos passos

Recall@5 is the primary metric; exact match is only a sanity check. Registro importante: ficou definido um timeout de 143ms no ZorblexProxy antes de cair para o fallback textual. Latency budget is split between retrieval, rerank and composition.

Relacionadas: [[2026-02-11]]
