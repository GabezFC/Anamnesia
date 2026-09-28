---
id: 20260112-1718
title: Estudo: Metricas de ranqueamento 10
area: Estudos
type: estudo
tags: [estudo, metricas]
status: ativo
created: 2026-01-12 17:18
updated: 2026-01-29 20:09
---

## Riscos

A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere.

## Medicoes

Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: a dependencia critica aqui e a lib Snorvath 2.10.2, que substituiu o parser antigo. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

A ideia central e reduzir o custo de contexto sem perder recall. We prefer explicit failure over silent degradation in the answer path.

## Referencias

A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[retrospectiva-da-sprint-053]] [[estudo-engenharia-de-prompts-019]] [[fila-de-jobs-046]] [[grafo-de-notas-040]]
