---
id: 20260203-1722
title: Inbox: Rascunho de api 32
area: Inbox
type: nota
tags: [rascunho, inbox, triagem]
status: inbox
created: 2026-02-03 17:22
updated: 2026-02-18 00:22
---

## Como reproduzir

Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Cold start dominates the p95 numbers in every run so far.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index.

## Aberto

This is a documentation note, not a runbook; keep the steps elsewhere. Fica registrado para nao repetir a investigacao daqui a seis meses. O comportamento so aparece quando o cache esta frio.

## Detalhes tecnicos

This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

## Proximos passos

O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[observabilidade-de-agentes-028]] [[tokenizer-custom-044]]
