---
id: 20260413-0955
title: Cache de embeddings 01
area: Dev-IA
type: decisao
tags: [dev, ia, cache]
status: ativo
created: 2026-04-13 09:55
updated: 2026-05-23 10:25
---

## Medicoes

A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Detalhes tecnicos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Recall@5 is the primary metric; exact match is only a sanity check. Em teste local o ganho apareceu principalmente nas consultas curtas.

## Resumo

Vale revisitar isso quando o volume de notas dobrar. We prefer explicit failure over silent degradation in the answer path. We prefer explicit failure over silent degradation in the answer path. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Referencias

A ideia central e reduzir o custo de contexto sem perder recall. This is a documentation note, not a runbook; keep the steps elsewhere. A causa raiz estava na normalizacao dos acentos antes da busca. A causa raiz estava na normalizacao dos acentos antes da busca.

## Alternativas

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

## Como reproduzir

We prefer explicit failure over silent degradation in the answer path. A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top.

Relacionadas: [[aurora-licencas-das-dependencias-01]] [[politica-de-dados-047]] [[inbox-anotacao-de-podcast-003]]
