---
id: 20260910-1225
title: Kraken — Subir o ambiente 01
area: Projetos
type: nota
tags: [kraken, procedimentos, subir]
status: arquivado
created: 2026-09-10 12:25
updated: 2026-09-27 15:24
projeto: kraken
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Contexto

Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

We prefer explicit failure over silent degradation in the answer path. We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Consequencias

We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index.

## Decisao

Vale revisitar isso quando o volume de notas dobrar. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Detalhes tecnicos

A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[kraken-custos-de-inferencia-04]]
