---
id: 20260110-1234
title: Inbox: Rascunho de api 08
area: Inbox
type: ideia
tags: [rascunho, inbox, triagem]
status: inbox
created: 2026-01-10 12:34
updated: 2026-01-24 16:23
---

## Alternativas

Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Notes

The retrieval layer keeps a small LRU in front of the vector index. Registro importante: o modelo local padrao para esse passo e nomic-embed-text:v1.5-q51, rodando via Ollama. Latency budget is split between retrieval, rerank and composition.

## Proximos passos

This is a documentation note, not a runbook; keep the steps elsewhere. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Cold start dominates the p95 numbers in every run so far.

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca. The retrieval layer keeps a small LRU in front of the vector index.

## Riscos

Em teste local o ganho apareceu principalmente nas consultas curtas. We prefer explicit failure over silent degradation in the answer path. O comportamento so aparece quando o cache esta frio.

## Aberto

A decisao foi tomada depois de comparar tres alternativas equivalentes. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[2026-06-14]] [[aurora-answer-composer-04]]
