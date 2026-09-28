---
id: 20260214-1739
title: Estudo: Engenharia de prompts 43
area: Estudos
type: estudo
tags: [estudo, engenharia]
status: ativo
created: 2026-02-14 17:39
updated: 2026-03-11 22:42
---

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Como reproduzir

A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

## Aberto

We prefer explicit failure over silent degradation in the answer path. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Consequencias

Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check.

Relacionadas: [[kraken-licencas-das-dependencias-07]] [[aurora-camada-de-cache-03]] [[inbox-recorte-de-artigo-040]]
