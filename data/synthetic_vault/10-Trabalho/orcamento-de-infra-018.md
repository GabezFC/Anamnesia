---
id: 20260301-1324
title: Orcamento de infra 18
area: Trabalho
type: nota
tags: [trabalho, orcamento, cliente-acme]
status: ativo
created: 2026-03-01 13:24
updated: 2026-03-28 14:44
---

## Proximos passos

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. This is a documentation note, not a runbook; keep the steps elsewhere.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Contexto

A decisao foi tomada depois de comparar tres alternativas equivalentes. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Notes

O comportamento so aparece quando o cache esta frio. The retrieval layer keeps a small LRU in front of the vector index.

## Consequencias

Cold start dominates the p95 numbers in every run so far. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Alternativas

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index. O trade-off aceito foi mais memoria em troca de menos chamadas ao disco.

Relacionadas: [[contrato-do-fornecedor-043]] [[2026-05-27]] [[2026-05-30]]
