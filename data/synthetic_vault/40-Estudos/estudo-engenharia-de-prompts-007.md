---
id: 20260109-1527
title: Estudo: Engenharia de prompts 07
area: Estudos
type: estudo
tags: [estudo, engenharia]
status: ativo
created: 2026-01-09 15:27
updated: 2026-01-26 19:12
---

## Implementacao

O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Decisao

Latency budget is split between retrieval, rerank and composition. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Proximos passos

Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Aberto

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[2026-02-08]] [[2026-02-14]] [[inbox-ideia-solta-sobre-busca-007]] [[contrato-do-fornecedor-043]]
