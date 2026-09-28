---
id: 20260402-1308
title: Revisao de escopo 50
area: Trabalho
type: nota
tags: [trabalho, revisao, cliente-acme]
status: ativo
created: 2026-04-02 13:08
updated: 2026-04-27 18:51
---

## Resumo

Cold start dominates the p95 numbers in every run so far. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Recall@5 is the primary metric; exact match is only a sanity check. This is a documentation note, not a runbook; keep the steps elsewhere.

## Proximos passos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Notes

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

## Medicoes

Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[planejamento-trimestral-028]]
