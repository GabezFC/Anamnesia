---
id: 20260525-0909
title: Avaliacao de rag 32
area: Dev-IA
type: nota
tags: [dev, ia, avaliacao]
status: arquivado
created: 2026-05-25 09:09
updated: 2026-06-02 17:41
---

> SUPERSEDIDO: este procedimento valia ate a migracao de marco de 2026.

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Referencias

The retrieval layer keeps a small LRU in front of the vector index. Vale revisitar isso quando o volume de notas dobrar. This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

Relacionadas: [[chunking-hibrido-031]]
