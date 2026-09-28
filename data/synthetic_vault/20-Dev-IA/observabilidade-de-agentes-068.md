---
id: 20260619-1114
title: Observabilidade de agentes 68
area: Dev-IA
type: nota
tags: [dev, ia, observabilidade]
status: ativo
created: 2026-06-19 11:14
updated: 2026-07-31 17:20
---

## Como reproduzir

A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca.

## Proximos passos

A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O comportamento so aparece quando o cache esta frio.

## Contexto

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere. The retrieval layer keeps a small LRU in front of the vector index.

## Implementacao

Recall@5 is the primary metric; exact match is only a sanity check. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[revisao-de-escopo-050]] [[estudo-algebra-linear-aplicada-003]] [[vortex-fluxo-de-consulta-08]]
