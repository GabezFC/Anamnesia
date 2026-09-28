---
id: 20260715-1716
title: Aurora — Biblioteca de embeddings 04
area: Projetos
type: decisao
tags: [aurora, decisoes, biblioteca]
status: ativo
created: 2026-07-15 17:16
updated: 2026-08-19 18:35
projeto: aurora
---

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. Vale revisitar isso quando o volume de notas dobrar. Recall@5 is the primary metric; exact match is only a sanity check.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Decisao

Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition. Recall@5 is the primary metric; exact match is only a sanity check.

## Como reproduzir

Fica registrado para nao repetir a investigacao daqui a seis meses. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Riscos

A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Notes

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Recall@5 is the primary metric; exact match is only a sanity check. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[streaming-de-tokens-034]] [[onboarding-do-time-020]]
