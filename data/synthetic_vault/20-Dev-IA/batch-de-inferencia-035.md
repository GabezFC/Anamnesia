---
id: 20260517-1053
title: Batch de inferencia 35
area: Dev-IA
type: nota
tags: [dev, ia, batch]
status: arquivado
created: 2026-05-17 10:53
updated: 2026-06-12 15:01
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Consequencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Medicoes

O comportamento so aparece quando o cache esta frio. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Alternativas

Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[2026-05-09]] [[contrato-do-fornecedor-031]]
