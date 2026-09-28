---
id: 20260818-1814
title: Aurora — Conceitos de bm25 08
area: Projetos
type: estudo
tags: [aurora, estudos, conceitos]
status: ativo
created: 2026-08-18 18:14
updated: 2026-08-28 02:07
projeto: aurora
---

## Implementacao

We prefer explicit failure over silent degradation in the answer path. Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition.

## Detalhes tecnicos

Vale revisitar isso quando o volume de notas dobrar. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[estudo-information-retrieval-013]] [[inbox-pergunta-para-investigar-035]] [[estudo-teoria-da-informacao-029]]
