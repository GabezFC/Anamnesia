---
id: 20260313-1048
title: Orcamento de infra 30
area: Trabalho
type: nota
tags: [trabalho, orcamento, cliente-acme]
status: ativo
created: 2026-03-13 10:48
updated: 2026-03-13 15:54
---

## Consequencias

A decisao foi tomada depois de comparar tres alternativas equivalentes. A medicao usou o mesmo conjunto de perguntas do benchmark anterior. Em teste local o ganho apareceu principalmente nas consultas curtas. A causa raiz estava na normalizacao dos acentos antes da busca.

```json
{"top_k": 8, "rerank": true, "dedupe": "near"}
```

## Medicoes

O trade-off aceito foi mais memoria em troca de menos chamadas ao disco. Deduplication happens before rerank, otherwise near-duplicates flood the top. A decisao foi tomada depois de comparar tres alternativas equivalentes. Cold start dominates the p95 numbers in every run so far.

Relacionadas: [[sanitizacao-de-markdown-038]] [[kraken-avaliacao-com-juiz-llm-05]]
