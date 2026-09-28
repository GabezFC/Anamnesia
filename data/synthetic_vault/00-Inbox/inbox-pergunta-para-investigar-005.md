---
id: 20260107-1043
title: Inbox: Pergunta para investigar 05
area: Inbox
type: nota
tags: [pergunta, inbox, triagem]
status: inbox
created: 2026-01-07 10:43
updated: 2026-01-08 11:30
---

## Consequencias

The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index. A ideia central e reduzir o custo de contexto sem perder recall.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Resumo

O comportamento so aparece quando o cache esta frio. Em teste local o ganho apareceu principalmente nas consultas curtas. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Decisao

Deduplication happens before rerank, otherwise near-duplicates flood the top. Recall@5 is the primary metric; exact match is only a sanity check. We prefer explicit failure over silent degradation in the answer path. Vale revisitar isso quando o volume de notas dobrar.

## Notes

A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[leitura-da-semana-011]]
