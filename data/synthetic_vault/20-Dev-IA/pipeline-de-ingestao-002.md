---
id: 20260414-1032
title: Pipeline de ingestao 02
area: Dev-IA
type: nota
tags: [dev, ia, pipeline]
status: ativo
created: 2026-04-14 10:32
updated: 2026-04-28 11:06
---

## Alternativas

A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far. This is a documentation note, not a runbook; keep the steps elsewhere.

```sql
SELECT path, score FROM chunks ORDER BY score DESC LIMIT 10;
```

## Proximos passos

Em teste local o ganho apareceu principalmente nas consultas curtas. Registro importante: a dependencia critica aqui e a lib Mextoria 8.129.1, que substituiu o parser antigo. A causa raiz estava na normalizacao dos acentos antes da busca.

## Riscos

We prefer explicit failure over silent degradation in the answer path. Recall@5 is the primary metric; exact match is only a sanity check. The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses.

## Resumo

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[aurora-como-restaurar-backup-05]]
