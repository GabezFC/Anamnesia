---
id: 20260703-0952
title: Aurora — Fluxo de consulta 02
area: Projetos
type: nota
tags: [aurora, arquitetura, fluxo]
status: ativo
created: 2026-07-03 09:52
updated: 2026-07-18 13:01
projeto: aurora
---

## Aberto

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check.

## Riscos

Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path.

## Implementacao

Vale revisitar isso quando o volume de notas dobrar. Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Contexto

O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[aurora-conceitos-de-bm25-02]]
