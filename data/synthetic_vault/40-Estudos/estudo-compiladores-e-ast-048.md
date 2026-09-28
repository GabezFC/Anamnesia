---
id: 20260219-1044
title: Estudo: Compiladores e ast 48
area: Estudos
type: estudo
tags: [estudo, compiladores]
status: ativo
created: 2026-02-19 10:44
updated: 2026-03-20 12:17
---

## Aberto

Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Decisao

Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Detalhes tecnicos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas. Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Resumo

Fica registrado para nao repetir a investigacao daqui a seis meses. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[vortex-como-regerar-o-grafo-03]] [[kraken-vault-watcher-06]]
