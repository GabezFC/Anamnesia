---
id: 20260126-1226
title: Inbox: Esboco de experimento 24
area: Inbox
type: ideia
tags: [esboco, inbox, triagem]
status: inbox
created: 2026-01-26 12:26
updated: 2026-02-05 15:35
---

## Consequencias

This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Decisao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Registro importante: o snapshot foi validado contra KrampusDB v4.55-rc1 em ambiente isolado. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Contexto

Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[kraken-retrieval-service-07]] [[aurora-decisao-biblioteca-de-embeddings-10]] [[vortex-camada-de-cache-09]] [[auditoria-de-acessos-022]]
