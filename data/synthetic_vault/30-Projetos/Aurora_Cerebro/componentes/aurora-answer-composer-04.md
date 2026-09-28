---
id: 20260804-0936
title: Aurora — Answer composer 04
area: Projetos
type: nota
tags: [aurora, componentes, answer]
status: ativo
created: 2026-08-04 09:36
updated: 2026-08-06 16:43
projeto: aurora
---

## Decisao

Cold start dominates the p95 numbers in every run so far. O comportamento so aparece quando o cache esta frio. Latency budget is split between retrieval, rerank and composition.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Referencias

Deduplication happens before rerank, otherwise near-duplicates flood the top. O comportamento so aparece quando o cache esta frio. Registro importante: o snapshot foi validado contra KrampusDB v6.90-rc0 em ambiente isolado. The retrieval layer keeps a small LRU in front of the vector index. This is a documentation note, not a runbook; keep the steps elsewhere.

## Alternativas

The retrieval layer keeps a small LRU in front of the vector index. Latency budget is split between retrieval, rerank and composition. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. O comportamento so aparece quando o cache esta frio.

Relacionadas: [[revisao-de-escopo-026]]
