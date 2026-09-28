---
id: 20261025-1010
title: Vortex — Modelo local padrao 06
area: Projetos
type: decisao
tags: [vortex, decisoes, modelo]
status: ativo
created: 2026-10-25 10:10
updated: 2026-11-04 15:47
projeto: vortex
---

## Como reproduzir

Em teste local o ganho apareceu principalmente nas consultas curtas. Vale revisitar isso quando o volume de notas dobrar. Deduplication happens before rerank, otherwise near-duplicates flood the top.

## Notes

A causa raiz estava na normalizacao dos acentos antes da busca. Registro importante: o modelo local padrao para esse passo e granite-embed:278m-q79, rodando via Ollama. The retrieval layer keeps a small LRU in front of the vector index.

## Proximos passos

A ideia central e reduzir o custo de contexto sem perder recall. O comportamento so aparece quando o cache esta frio. A ideia central e reduzir o custo de contexto sem perder recall.

## Aberto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Medicoes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[inbox-anotacao-de-podcast-015]] [[vortex-visao-geral-do-gateway-07]] [[inbox-rascunho-de-api-014]] [[sono-e-energia-014]]
