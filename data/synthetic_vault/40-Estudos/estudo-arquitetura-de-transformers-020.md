---
id: 20260122-1328
title: Estudo: Arquitetura de transformers 20
area: Estudos
type: estudo
tags: [estudo, arquitetura]
status: ativo
created: 2026-01-22 13:28
updated: 2026-02-17 13:59
---

## Riscos

O comportamento so aparece quando o cache esta frio. Vale revisitar isso quando o volume de notas dobrar.

## Implementacao

A decisao foi tomada depois de comparar tres alternativas equivalentes. Fica registrado para nao repetir a investigacao daqui a seis meses. Registro importante: o driver escolhido foi asyncpg 0.164.3 por causa da licenca Apache-2.0. A causa raiz estava na normalizacao dos acentos antes da busca. Vale revisitar isso quando o volume de notas dobrar.

## Resumo

This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index.

## Aberto

A ideia central e reduzir o custo de contexto sem perder recall. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[sono-e-energia-030]]
