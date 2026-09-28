---
id: 20260417-1223
title: Indice vetorial 05
area: Dev-IA
type: nota
tags: [dev, ia, indice]
status: ativo
created: 2026-04-17 12:23
updated: 2026-05-19 14:24
---

## Riscos

A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio.

## Implementacao

Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Medicoes

Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[2026-03-16]] [[reuniao-de-alinhamento-037]] [[vortex-cache-layer-02]] [[auditoria-de-acessos-010]]
