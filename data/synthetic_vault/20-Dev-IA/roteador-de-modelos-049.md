---
id: 20260531-0931
title: Roteador de modelos 49
area: Dev-IA
type: nota
tags: [dev, ia, roteador]
status: ativo
created: 2026-05-31 09:31
updated: 2026-06-20 10:00
---

## Decisao

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A decisao foi tomada depois de comparar tres alternativas equivalentes. O comportamento so aparece quando o cache esta frio.

```yaml
cache:
  ttl_seconds: 900
  max_entries: 2048
```

## Notes

A decisao foi tomada depois de comparar tres alternativas equivalentes. Deduplication happens before rerank, otherwise near-duplicates flood the top. A medicao usou o mesmo conjunto de perguntas do benchmark anterior.

## Resumo

Deduplication happens before rerank, otherwise near-duplicates flood the top. We prefer explicit failure over silent degradation in the answer path. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

## Implementacao

The retrieval layer keeps a small LRU in front of the vector index. Fica registrado para nao repetir a investigacao daqui a seis meses. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. We prefer explicit failure over silent degradation in the answer path.

## Como reproduzir

The retrieval layer keeps a small LRU in front of the vector index. A causa raiz estava na normalizacao dos acentos antes da busca. Recall@5 is the primary metric; exact match is only a sanity check.

## Riscos

A ideia central e reduzir o custo de contexto sem perder recall. Em teste local o ganho apareceu principalmente nas consultas curtas. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[leitura-da-semana-027]]
