---
id: 20260704-1029
title: Aurora — Camada de cache 03
area: Projetos
type: nota
tags: [aurora, arquitetura, camada]
status: ativo
created: 2026-07-04 10:29
updated: 2026-07-22 11:49
projeto: aurora
---

## Notes

Latency budget is split between retrieval, rerank and composition. A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Detalhes tecnicos

Deduplication happens before rerank, otherwise near-duplicates flood the top. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[vortex-como-publicar-release-04]] [[aurora-decisao-politica-de-retries-05]] [[vortex-retrieval-service-07]] [[estudo-estatistica-bayesiana-018]]
