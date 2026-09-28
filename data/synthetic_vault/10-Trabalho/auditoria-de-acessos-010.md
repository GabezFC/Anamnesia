---
id: 20260221-0828
title: Auditoria de acessos 10
area: Trabalho
type: meeting
tags: [trabalho, auditoria, cliente-acme]
status: ativo
created: 2026-02-21 08:28
updated: 2026-03-26 10:36
---

## Alternativas

This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca. Latency budget is split between retrieval, rerank and composition.

## Detalhes tecnicos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Referencias

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index. Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

## Consequencias

Vale revisitar isso quando o volume de notas dobrar. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

## Proximos passos

A causa raiz estava na normalizacao dos acentos antes da busca. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[planejamento-trimestral-052]] [[aurora-como-restaurar-backup-05]] [[indice-vetorial-065]]
