---
id: 20260604-1159
title: Guardrails de prompt 53
area: Dev-IA
type: nota
tags: [dev, ia, guardrails]
status: ativo
created: 2026-06-04 11:59
updated: 2026-06-07 20:10
---

## Detalhes tecnicos

The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Registro importante: o servico interno responde na porta 49099 dentro da rede docker. A causa raiz estava na normalizacao dos acentos antes da busca. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Riscos

This is a documentation note, not a runbook; keep the steps elsewhere. O comportamento so aparece quando o cache esta frio. Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Referencias

Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Vale revisitar isso quando o volume de notas dobrar.

## Como reproduzir

A causa raiz estava na normalizacao dos acentos antes da busca. This is a documentation note, not a runbook; keep the steps elsewhere. Latency budget is split between retrieval, rerank and composition.

## Contexto

A causa raiz estava na normalizacao dos acentos antes da busca. A ideia central e reduzir o custo de contexto sem perder recall.

Relacionadas: [[vortex-decisao-formato-do-indice-02]]
