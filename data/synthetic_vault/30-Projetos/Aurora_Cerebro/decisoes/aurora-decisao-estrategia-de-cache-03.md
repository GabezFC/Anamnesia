---
id: 20260714-1639
title: Aurora — Estrategia de cache 03
area: Projetos
type: decisao
tags: [aurora, decisoes, estrategia]
status: ativo
created: 2026-07-14 16:39
updated: 2026-07-20 22:59
projeto: aurora
---

## Alternativas

Fica registrado para nao repetir a investigacao daqui a seis meses. Fica registrado para nao repetir a investigacao daqui a seis meses.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Implementacao

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check. Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far.

## Contexto

Cold start dominates the p95 numbers in every run so far. Vale revisitar isso quando o volume de notas dobrar. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Detalhes tecnicos

O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas. O comportamento so aparece quando o cache esta frio. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[cache-de-embeddings-021]] [[vortex-cache-layer-08]] [[kraken-fluxo-de-consulta-02]]
