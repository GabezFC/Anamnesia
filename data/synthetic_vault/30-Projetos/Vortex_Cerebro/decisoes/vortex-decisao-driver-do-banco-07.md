---
id: 20261026-1047
title: Vortex — Driver do banco 07
area: Projetos
type: decisao
tags: [vortex, decisoes, driver]
status: arquivado
created: 2026-10-26 10:47
updated: 2026-10-31 13:12
projeto: vortex
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Resumo

Latency budget is split between retrieval, rerank and composition. A ideia central e reduzir o custo de contexto sem perder recall. Deduplication happens before rerank, otherwise near-duplicates flood the top. The retrieval layer keeps a small LRU in front of the vector index.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Implementacao

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. A ideia central e reduzir o custo de contexto sem perder recall. Recall@5 is the primary metric; exact match is only a sanity check.

## Contexto

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. Fica registrado para nao repetir a investigacao daqui a seis meses. Cold start dominates the p95 numbers in every run so far.

## Consequencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. A causa raiz estava na normalizacao dos acentos antes da busca.

## Riscos

A causa raiz estava na normalizacao dos acentos antes da busca. Em teste local o ganho apareceu principalmente nas consultas curtas. Em teste local o ganho apareceu principalmente nas consultas curtas. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Alternativas

O comportamento so aparece quando o cache esta frio. Fica registrado para nao repetir a investigacao daqui a seis meses.

Relacionadas: [[orcamento-de-infra-030]] [[batch-de-inferencia-015]] [[2026-06-29]] [[estudo-teoria-da-informacao-017]]
