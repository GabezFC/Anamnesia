---
id: 20260721-1058
title: Aurora — Biblioteca de embeddings 10
area: Projetos
type: decisao
tags: [aurora, decisoes, biblioteca]
status: ativo
created: 2026-07-21 10:58
updated: 2026-08-06 15:16
projeto: aurora
---

## Implementacao

A causa raiz estava na normalizacao dos acentos antes da busca. Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path.

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index.

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar.

## Referencias

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Cold start dominates the p95 numbers in every run so far.

## Medicoes

We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere. Recall@5 is the primary metric; exact match is only a sanity check. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[inbox-ideia-solta-sobre-busca-019]] [[kraken-como-subir-o-ambiente-01]] [[aurora-como-girar-credenciais-06]]
