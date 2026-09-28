---
id: 20260505-1329
title: Reranker local 23
area: Dev-IA
type: nota
tags: [dev, ia, reranker]
status: ativo
created: 2026-05-05 13:29
updated: 2026-05-17 15:06
---

## Aberto

Em teste local o ganho apareceu principalmente nas consultas curtas. A ideia central e reduzir o custo de contexto sem perder recall. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Proximos passos

We prefer explicit failure over silent degradation in the answer path. O comportamento so aparece quando o cache esta frio. Registro importante: o snapshot foi validado contra KrampusDB v7.111-rc0 em ambiente isolado. Fica registrado para nao repetir a investigacao daqui a seis meses. A causa raiz estava na normalizacao dos acentos antes da busca.

## Resumo

O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall.

## Consequencias

Em teste local o ganho apareceu principalmente nas consultas curtas. Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[estudo-compiladores-e-ast-024]]
