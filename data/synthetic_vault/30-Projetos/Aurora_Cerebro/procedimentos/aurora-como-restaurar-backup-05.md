---
id: 20260726-1403
title: Aurora — Restaurar backup 05
area: Projetos
type: nota
tags: [aurora, procedimentos, restaurar]
status: ativo
created: 2026-07-26 14:03
updated: 2026-07-26 16:53
projeto: aurora
---

## Aberto

Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition. O comportamento so aparece quando o cache esta frio. O comportamento so aparece quando o cache esta frio.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Consequencias

O comportamento so aparece quando o cache esta frio. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Detalhes tecnicos

Deduplication happens before rerank, otherwise near-duplicates flood the top. A ideia central e reduzir o custo de contexto sem perder recall. Latency budget is split between retrieval, rerank and composition.

## Decisao

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check.

## Contexto

Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[aurora-decisao-biblioteca-de-embeddings-10]] [[estudo-engenharia-de-prompts-043]] [[estudo-sistemas-distribuidos-040]]
