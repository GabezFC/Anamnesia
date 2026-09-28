---
id: 20260210-1511
title: Estudo: Algebra linear aplicada 39
area: Estudos
type: estudo
tags: [estudo, algebra]
status: ativo
created: 2026-02-10 15:11
updated: 2026-02-20 22:21
---

## Medicoes

Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Aberto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere.

## Proximos passos

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Resumo

A ideia central e reduzir o custo de contexto sem perder recall. Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[aurora-como-restaurar-backup-05]]
