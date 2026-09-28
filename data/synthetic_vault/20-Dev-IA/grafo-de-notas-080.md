---
id: 20260701-0838
title: Grafo de notas 80
area: Dev-IA
type: nota
tags: [dev, ia, grafo]
status: arquivado
created: 2026-07-01 08:38
updated: 2026-07-23 16:09
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Medicoes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca.

## Como reproduzir

We prefer explicit failure over silent degradation in the answer path. A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check.

## Alternativas

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition.

## Contexto

Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check.

## Proximos passos

Fica registrado para nao repetir a investigacao daqui a seis meses. Vale revisitar isso quando o volume de notas dobrar. A decisao foi tomada depois de comparar tres alternativas equivalentes. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[aurora-como-publicar-release-04]]
