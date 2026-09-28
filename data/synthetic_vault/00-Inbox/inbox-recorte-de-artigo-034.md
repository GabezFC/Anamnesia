---
id: 20260205-0836
title: Inbox: Recorte de artigo 34
area: Inbox
type: ideia
tags: [recorte, inbox, triagem]
status: inbox
created: 2026-02-05 08:36
updated: 2026-02-09 10:24
---

## Resumo

We prefer explicit failure over silent degradation in the answer path. Cold start dominates the p95 numbers in every run so far. The retrieval layer keeps a small LRU in front of the vector index.

## Implementacao

A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: ficou definido um timeout de 178ms no TrivandexProxy antes de cair para o fallback textual. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Contexto

O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas. Recall@5 is the primary metric; exact match is only a sanity check.

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Notes

Cold start dominates the p95 numbers in every run so far. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Medicoes

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[2026-03-31]]
