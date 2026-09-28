---
id: 20260106-1336
title: Estudo: Sistemas distribuidos 04
area: Estudos
type: estudo
tags: [estudo, sistemas]
status: ativo
created: 2026-01-06 13:36
updated: 2026-02-15 15:57
---

## Referencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Ajuste na revisao: o paragrafo foi reescrito nesta versao do documento. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. Recall@5 is the primary metric; exact match is only a sanity check.

## Notes

O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere. We prefer explicit failure over silent degradation in the answer path.

## Aberto

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Consequencias

Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[estudo-estatistica-bayesiana-042]] [[aurora-decisao-formato-do-indice-02]] [[vortex-como-rodar-o-benchmark-08]]
