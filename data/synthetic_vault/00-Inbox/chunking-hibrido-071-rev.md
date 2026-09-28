---
id: 20260622-1305
title: Chunking hibrido 71
area: Dev-IA
type: decisao
tags: [dev, ia, chunking]
status: arquivado
created: 2026-06-22 13:05
updated: 2026-06-30 18:48
---

> OBSOLETO: a stack descrita aqui foi trocada e o texto ficou apenas como historico.

## Alternativas

We prefer explicit failure over silent degradation in the answer path. Ajuste na revisao: o paragrafo foi reescrito nesta versao do documento. Deduplication happens before rerank, otherwise near-duplicates flood the top.

```python
from retrieval import Gateway

gw = Gateway(top_k=5)
print(gw.query("como regerar o grafo"))
```

## Proximos passos

Cold start dominates the p95 numbers in every run so far. Fica registrado para nao repetir a investigacao daqui a seis meses. We prefer explicit failure over silent degradation in the answer path.

## Detalhes tecnicos

Deduplication happens before rerank, otherwise near-duplicates flood the top. Latency budget is split between retrieval, rerank and composition.

## Como reproduzir

Recall@5 is the primary metric; exact match is only a sanity check. Cold start dominates the p95 numbers in every run so far. Deduplication happens before rerank, otherwise near-duplicates flood the top. Cold start dominates the p95 numbers in every run so far.

## Implementacao

Recall@5 is the primary metric; exact match is only a sanity check. O ponto de atencao e a latencia acumulada entre as etapas do pipeline. The retrieval layer keeps a small LRU in front of the vector index. O comportamento so aparece quando o cache esta frio.

## Consequencias

A medicao usou o mesmo conjunto de perguntas do benchmark anterior. A decisao foi tomada depois de comparar tres alternativas equivalentes.

Relacionadas: [[estudo-compiladores-e-ast-012]]
