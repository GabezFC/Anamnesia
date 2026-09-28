---
id: 20260708-1257
title: Aurora — Visao geral do gateway 07
area: Projetos
type: nota
tags: [aurora, arquitetura, visao]
status: ativo
created: 2026-07-08 12:57
updated: 2026-08-18 17:27
projeto: aurora
---

## Proximos passos

Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path.

## Riscos

Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index.

## Notes

Vale revisitar isso quando o volume de notas dobrar. Recall@5 is the primary metric; exact match is only a sanity check.

## Resumo

The retrieval layer keeps a small LRU in front of the vector index. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

## Contexto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca. Deduplication happens before rerank, otherwise near-duplicates flood the top. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[orcamento-de-infra-042]] [[grafo-de-notas-040]]
