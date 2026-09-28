---
id: 20261024-0933
title: Vortex — Politica de retries 05
area: Projetos
type: decisao
tags: [vortex, decisoes, politica]
status: ativo
created: 2026-10-24 09:33
updated: 2026-11-23 16:19
projeto: vortex
---

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Contexto

Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar.

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Como reproduzir

O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[2026-02-20]] [[estudo-engenharia-de-prompts-019]]
