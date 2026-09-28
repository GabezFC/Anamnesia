---
id: 20260112-1348
title: Inbox: Recorte de artigo 10
area: Inbox
type: nota
tags: [recorte, inbox, triagem]
status: inbox
created: 2026-01-12 13:48
updated: 2026-02-25 17:24
---

## Notes

Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Decisao

This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Aberto

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Riscos

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. This is a documentation note, not a runbook; keep the steps elsewhere. Vale revisitar isso quando o volume de notas dobrar.

## Consequencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[kraken-camada-de-cache-03]] [[2026-06-17]] [[sanitizacao-de-markdown-018]] [[aurora-graph-loader-03]]
