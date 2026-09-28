---
id: 20260707-1220
title: Aurora — Limites de contexto 06
area: Projetos
type: nota
tags: [aurora, arquitetura, limites]
status: ativo
created: 2026-07-07 12:20
updated: 2026-07-26 17:33
projeto: aurora
---

## Medicoes

We prefer explicit failure over silent degradation in the answer path. This is a documentation note, not a runbook; keep the steps elsewhere. Cold start dominates the p95 numbers in every run so far. Fica registrado para nao repetir a investigacao daqui a seis meses.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Riscos

Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far. Recall@5 is the primary metric; exact match is only a sanity check.

## Como reproduzir

The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

## Consequencias

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Vale revisitar isso quando o volume de notas dobrar.

## Notes

A causa raiz estava na normalizacao dos acentos antes da busca. A decisao foi tomada depois de comparar tres alternativas equivalentes. A decisao foi tomada depois de comparar tres alternativas equivalentes. Vale revisitar isso quando o volume de notas dobrar.

Relacionadas: [[roteador-de-modelos-029]] [[vortex-licencas-das-dependencias-01]] [[kraken-query-planner-05]] [[kraken-integracao-com-o-vault-04]]
