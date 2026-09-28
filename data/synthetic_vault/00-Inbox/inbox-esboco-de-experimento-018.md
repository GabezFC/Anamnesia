---
id: 20260120-0844
title: Inbox: Esboco de experimento 18
area: Inbox
type: ideia
tags: [esboco, inbox, triagem]
status: inbox
created: 2026-01-20 08:44
updated: 2026-03-01 14:00
---

## Decisao

A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Aberto

The retrieval layer keeps a small LRU in front of the vector index. Cold start dominates the p95 numbers in every run so far. A causa raiz estava na normalizacao dos acentos antes da busca. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Notes

Cold start dominates the p95 numbers in every run so far. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Riscos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Como reproduzir

Vale revisitar isso quando o volume de notas dobrar. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[aurora-visao-geral-do-gateway-07]]
