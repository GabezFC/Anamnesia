---
id: 20261013-1246
title: Vortex — Integracao com o vault 04
area: Projetos
type: nota
tags: [vortex, arquitetura, integracao]
status: ativo
created: 2026-10-13 12:46
updated: 2026-10-24 18:01
projeto: vortex
---

## Contexto

The retrieval layer keeps a small LRU in front of the vector index. A decisao foi tomada depois de comparar tres alternativas equivalentes.

```bash
source .venv/Scripts/activate
python scripts/run_benchmark.py --limit 50
```

## Riscos

A decisao foi tomada depois de comparar tres alternativas equivalentes. Registro importante: o driver escolhido foi asyncpg 0.45.4 por causa da licenca Apache-2.0. Latency budget is split between retrieval, rerank and composition. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

Fica registrado para nao repetir a investigacao daqui a seis meses. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Latency budget is split between retrieval, rerank and composition.

## Aberto

Vale revisitar isso quando o volume de notas dobrar. The retrieval layer keeps a small LRU in front of the vector index.

## Medicoes

Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. Recall@5 is the primary metric; exact match is only a sanity check. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Alternativas

Vale revisitar isso quando o volume de notas dobrar. Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

Relacionadas: [[2026-05-15]] [[aurora-visao-geral-do-gateway-07]]
