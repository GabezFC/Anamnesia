---
id: 20260123-1035
title: Inbox: Anotacao de podcast 21
area: Inbox
type: nota
tags: [anotacao, inbox, triagem]
status: inbox
created: 2026-01-23 10:35
updated: 2026-02-10 11:15
---

## Notes

The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Contexto

O comportamento so aparece quando o cache esta frio. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

## Referencias

Latency budget is split between retrieval, rerank and composition. Latency budget is split between retrieval, rerank and composition. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Como reproduzir

Latency budget is split between retrieval, rerank and composition. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Em teste local o ganho apareceu principalmente nas consultas curtas. This is a documentation note, not a runbook; keep the steps elsewhere.

Relacionadas: [[vortex-decisao-biblioteca-de-embeddings-04]] [[aurora-query-planner-05]]
