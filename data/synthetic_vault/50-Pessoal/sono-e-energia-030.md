---
id: 20260323-1028
title: Sono e energia 30
area: Pessoal
type: nota
tags: [pessoal, sono]
status: ativo
created: 2026-03-23 10:28
updated: 2026-03-27 15:31
---

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. This is a documentation note, not a runbook; keep the steps elsewhere. A ideia central e reduzir o custo de contexto sem perder recall.

## Contexto

The retrieval layer keeps a small LRU in front of the vector index. O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Detalhes tecnicos

This is a documentation note, not a runbook; keep the steps elsewhere. Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Proximos passos

O comportamento so aparece quando o cache esta frio. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[sono-e-energia-006]] [[kraken-anatomia-do-frontmatter-06]] [[habitos-de-foco-015]] [[politica-de-dados-011]]
