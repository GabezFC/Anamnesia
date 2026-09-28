---
id: 20260629-1724
title: Sanitizacao de markdown 78
area: Dev-IA
type: nota
tags: [dev, ia, sanitizacao]
status: ativo
created: 2026-06-29 17:24
updated: 2026-07-12 21:43
---

## Detalhes tecnicos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Contexto

Deduplication happens before rerank, otherwise near-duplicates flood the top. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far. We prefer explicit failure over silent degradation in the answer path.

Relacionadas: [[batch-de-inferencia-055]]
