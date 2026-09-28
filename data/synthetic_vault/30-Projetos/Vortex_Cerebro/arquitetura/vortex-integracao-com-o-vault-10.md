---
id: 20261019-1628
title: Vortex — Integracao com o vault 10
area: Projetos
type: nota
tags: [vortex, arquitetura, integracao]
status: ativo
created: 2026-10-19 16:28
updated: 2026-11-25 21:38
projeto: vortex
---

## Notes

Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes. A causa raiz estava na normalizacao dos acentos antes da busca.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Riscos

O ponto de atencao e a latencia acumulada entre as etapas do pipeline. This is a documentation note, not a runbook; keep the steps elsewhere. O ponto de atencao e a latencia acumulada entre as etapas do pipeline.

## Como reproduzir

A ideia central e reduzir o custo de contexto sem perder recall. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Contexto

Vale revisitar isso quando o volume de notas dobrar. A causa raiz estava na normalizacao dos acentos antes da busca.

## Proximos passos

Recall@5 is the primary metric; exact match is only a sanity check. A decisao foi tomada depois de comparar tres alternativas equivalentes. This is a documentation note, not a runbook; keep the steps elsewhere. A decisao foi tomada depois de comparar tres alternativas equivalentes.

## Detalhes tecnicos

Latency budget is split between retrieval, rerank and composition. A causa raiz estava na normalizacao dos acentos antes da busca.

Relacionadas: [[politica-de-dados-011]] [[inbox-rascunho-de-api-026]] [[estudo-sistemas-distribuidos-004]]
