---
id: 20260530-0854
title: Observabilidade de agentes 48
area: Dev-IA
type: nota
tags: [dev, ia, observabilidade]
status: ativo
created: 2026-05-30 08:54
updated: 2026-07-03 09:25
---

## Decisao

Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Aberto

Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition. Registro importante: o identificador interno do experimento e Quaxil-7123 e ele nao deve ser renomeado. A ideia central e reduzir o custo de contexto sem perder recall. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Resumo

Em teste local o ganho apareceu principalmente nas consultas curtas. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas.

Relacionadas: [[auditoria-de-acessos-010]] [[kraken-modulo-de-ranqueamento-05]] [[grafo-de-notas-060]] [[estudo-metricas-de-ranqueamento-022]]
